-- G2 同步有界接收：包摘要不可变，请求与业务结果在同一事务提交。
create table teachbase_app.delivery_package (
  workspace_id uuid not null references teachbase_app.workspace(workspace_id),
  package_id uuid not null,
  delivery_digest char(64) not null,
  manifest_json jsonb not null,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  primary key(workspace_id, package_id),
  foreign key(workspace_id, created_by) references teachbase_app.workspace_member(workspace_id, user_id),
  check(delivery_digest ~ '^[0-9a-f]{64}$'),
  check(jsonb_typeof(manifest_json) = 'object')
);

create table teachbase_app.delivery_request (
  workspace_id uuid not null,
  import_request_id uuid not null,
  package_id uuid not null,
  delivery_digest char(64) not null,
  status varchar(20) not null,
  expected_items integer not null check(expected_items between 1 and 100),
  receipt_json jsonb,
  received_by uuid not null,
  received_at timestamptz not null default now(),
  completed_at timestamptz,
  primary key(workspace_id, import_request_id),
  foreign key(workspace_id, package_id) references teachbase_app.delivery_package(workspace_id, package_id),
  foreign key(workspace_id, received_by) references teachbase_app.workspace_member(workspace_id, user_id),
  check(delivery_digest ~ '^[0-9a-f]{64}$'),
  check(status in ('processing', 'succeeded')),
  check((status = 'processing' and receipt_json is null and completed_at is null)
     or (status = 'succeeded' and receipt_json is not null and jsonb_typeof(receipt_json) = 'object' and completed_at is not null))
);

create table teachbase_app.delivery_request_item (
  workspace_id uuid not null,
  import_request_id uuid not null,
  item_key varchar(512) not null,
  question_id uuid not null,
  question_revision_id uuid not null,
  review_case_id uuid not null,
  source_region_id uuid not null,
  delivery_content_hash char(64) not null,
  domain_content_hash char(64) not null,
  primary key(workspace_id, import_request_id, item_key),
  foreign key(workspace_id, import_request_id) references teachbase_app.delivery_request(workspace_id, import_request_id),
  foreign key(question_revision_id, question_id, workspace_id) references teachbase_app.question_revision(question_revision_id, question_id, workspace_id),
  foreign key(review_case_id, workspace_id) references teachbase_app.review_case(review_case_id, workspace_id),
  foreign key(source_region_id) references teachbase_app.source_region(source_region_id),
  check(delivery_content_hash ~ '^[0-9a-f]{64}$' and domain_content_hash ~ '^[0-9a-f]{64}$')
);

create table teachbase_app.delivery_package_file (
  workspace_id uuid not null,
  package_id uuid not null,
  file_key varchar(512) not null,
  file_version_id uuid not null,
  sha256 char(64) not null,
  is_referenced boolean not null,
  primary key(workspace_id, package_id, file_key),
  foreign key(workspace_id, package_id) references teachbase_app.delivery_package(workspace_id, package_id),
  foreign key(file_version_id, workspace_id) references teachbase_app.file_version(file_version_id, workspace_id)
);

-- [jooq ignore start]
-- processing 只允许在未提交事务内存在；成功 receipt 的逐项身份/哈希必须与真实业务行对应。
create function teachbase_app.verify_delivery_receipt() returns trigger language plpgsql as $$
declare r teachbase_app.delivery_request; actual_count integer;
begin
  select * into r from teachbase_app.delivery_request
    where workspace_id = new.workspace_id and import_request_id = new.import_request_id;
  if not found then return null; end if;
  select count(*) into actual_count from teachbase_app.delivery_request_item
    where workspace_id = r.workspace_id and import_request_id = r.import_request_id;
  if r.status <> 'succeeded' or actual_count <> r.expected_items
     or coalesce(jsonb_array_length(r.receipt_json->'items'), -1) <> r.expected_items
     or r.receipt_json->>'importRequestId' is distinct from r.import_request_id::text
     or r.receipt_json->>'deliveryDigest' is distinct from r.delivery_digest::text
     or exists (
       select 1 from teachbase_app.delivery_request_item i
       join teachbase_app.question_revision q on q.question_revision_id=i.question_revision_id
       join teachbase_app.review_case c on c.review_case_id=i.review_case_id
       left join teachbase_app.question_source_link s on s.question_revision_id=i.question_revision_id
       where i.workspace_id=r.workspace_id and i.import_request_id=r.import_request_id
       and (q.content_hash <> i.domain_content_hash or c.question_revision_id <> i.question_revision_id
         or s.source_region_id is distinct from i.source_region_id
         or not r.receipt_json->'items' @> jsonb_build_array(jsonb_build_object(
            'itemKey', i.item_key, 'questionId', i.question_id, 'questionRevisionId', i.question_revision_id,
            'reviewCaseId', i.review_case_id, 'sourceRegionId', i.source_region_id,
            'contentHash', i.delivery_content_hash, 'domainContentHash', i.domain_content_hash))))
  then raise exception 'delivery_receipt_incomplete' using errcode='23514'; end if;
  return null;
end $$;
create constraint trigger delivery_receipt_complete after insert or update on teachbase_app.delivery_request
  deferrable initially deferred for each row execute function teachbase_app.verify_delivery_receipt();
create constraint trigger delivery_item_receipt_complete after insert on teachbase_app.delivery_request_item
  deferrable initially deferred for each row execute function teachbase_app.verify_delivery_receipt();
-- 已成功的接收历史不能被修改；测试故障与回退也必须通过事务而非删改已成功 receipt。
create function teachbase_app.immutable_delivery_row() returns trigger language plpgsql as $$
begin raise exception 'delivery_history_immutable' using errcode='23514'; end $$;
create trigger delivery_package_immutable before update or delete on teachbase_app.delivery_package
  for each row execute function teachbase_app.immutable_delivery_row();
create trigger delivery_item_immutable before update or delete on teachbase_app.delivery_request_item
  for each row execute function teachbase_app.immutable_delivery_row();
create trigger delivery_file_immutable before update or delete on teachbase_app.delivery_package_file
  for each row execute function teachbase_app.immutable_delivery_row();
create trigger delivery_request_immutable before update or delete on teachbase_app.delivery_request
  for each row when (old.status = 'succeeded') execute function teachbase_app.immutable_delivery_row();
-- [jooq ignore stop]
