require "json"
require "mathtype_to_mathml_plus"

input_path = ARGV[0]
unless input_path && File.exist?(input_path)
  warn "usage: ruby_mtef_to_mathml_batch.rb batch_input.json"
  exit 2
end

input = JSON.parse(File.read(input_path, encoding: "UTF-8"))
records = []

(input["files"] || []).each do |item|
  path = item["path"].to_s
  record = {
    "ole_rid" => item["ole_rid"],
    "ole_object" => item["ole_object"],
    "path" => path,
    "status" => nil,
    "mathml" => nil,
    "error" => nil
  }
  begin
    mathml = MathTypeToMathMLPlus::Converter.new(path).convert
    if mathml && mathml.include?("<math")
      record["status"] = "mathml_ok"
      record["mathml"] = mathml
    else
      record["status"] = "mathml_missing_root"
      record["error"] = mathml.to_s[0, 500]
    end
  rescue StandardError => e
    record["status"] = "mtef_to_mathml_failed"
    record["error"] = "#{e.class}: #{e.message}"
  end
  records << record
end

puts JSON.generate({
  "schema_version" => "docx_legacy_mtef_mathml_batch.v0.1",
  "backend" => "ruby:mathtype_to_mathml_plus",
  "records" => records
})
