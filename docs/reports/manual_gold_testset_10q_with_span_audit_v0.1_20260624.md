# 10题人工金标测试集与二次 Span 审查 v0.1

日期：2026-06-24

## 样本范围

本次人工金标测试集共 10 题：

### 高中数学 5 题

1. `tq_002` 考点1 例题讲解 Q2
2. `tq_003` 考点1 例题讲解 Q3
3. `tq_010` 考点2 例题讲解 Q2
4. `tq_018` 考点3 例题讲解 Q1
5. `tq_025` 考点4 例题讲解 Q1

### 初中几何 5 题

6. `tq_002` 考点1 强化训练 变式1-1
7. `tq_004` 考点1 强化训练 变式2-1
8. `tq_009` 考点3 例题讲解 例5
9. `tq_021` 考点3 例题讲解 例9
10. `tq_030` 考点3 课后落实 课后1

说明：

- `Pass 1` 是我直接对着整题图做的原始 Markdown 抄录。
- `Span Audit` 是我对可疑局部再次核查的审查记录。
- `Pass 2` 是按二次 span 精修后的终稿，公式转成标准 LaTeX，正文保留 Markdown。

---

## 1. 高中数学 `tq_002`

题图：

- [tq_002_考点1：正余弦定理及其应用_例题讲解_Q2.png](/C:/Users/EDY/Documents/教研基建/outputs/ingress_splitter_v0.1/codex_profile_senior_math_transcription_v03_20260624/question_crops/tq_002_考点1：正余弦定理及其应用_例题讲解_Q2.png)

### Pass 1

```md
2.（2023·全国）在△ABC中，A = 2B，a = 6，b = 4，则 cos B = ____。

【答案】3/4

【解析】解：在△ABC中，A = 2B，a = 6，b = 4，
则 a / sin A = b / sin B，
即 6 / sin 2B = 4 / sin B，
解得 cos B = 3/4。
故答案为：3/4。
```

### Span Audit

- `sp_q2_01`：答案分式，复核图见 [q2_answer_fraction.png](/C:/Users/EDY/Documents/教研基建/tmp/manual_transcription_spans/q2_answer_fraction.png)
- `sp_q2_02`：解析核心公式，复核图见 [q2_analysis_formula.png](/C:/Users/EDY/Documents/教研基建/tmp/manual_transcription_spans/q2_analysis_formula.png)
- 审查结论：首轮无实质性错误，只需把分式和正弦关系转成标准 LaTeX。

### Pass 2

```md
2.（2023·全国）在 $\triangle ABC$ 中，$A=2B$，$a=6$，$b=4$，则 $\cos B=\underline{\hspace{1.5em}}$。

**答案**：$\dfrac{3}{4}$

**解析**：

由正弦定理，

$$
\frac{a}{\sin A}=\frac{b}{\sin B}
$$

代入 $A=2B,\ a=6,\ b=4$，得

$$
\frac{6}{\sin 2B}=\frac{4}{\sin B}
$$

又因为

$$
\sin 2B=2\sin B\cos B
$$

所以

$$
\frac{6}{2\sin B\cos B}=\frac{4}{\sin B}
$$

解得

$$
\cos B=\frac{3}{4}
$$

故答案为 $\dfrac{3}{4}$。
```

---

## 2. 高中数学 `tq_003`

题图：

- [tq_003_考点1：正余弦定理及其应用_例题讲解_Q3.png](/C:/Users/EDY/Documents/教研基建/outputs/ingress_splitter_v0.1/codex_profile_senior_math_transcription_v03_20260624/question_crops/tq_003_考点1：正余弦定理及其应用_例题讲解_Q3.png)

### Pass 1

```md
3.（2020·新课标Ⅲ）在△ABC中，cos C = 2/3，AC = 4，BC = 3，则 tan B =（ ）

A. √5
B. 2√5
C. 4√5
D. 8√5

【答案】C

【解析】解：∵ cos C = 2/3，AC = 4，BC = 3，
∴ tan C = √(1 / cos²C - 1) = √5 / 2，
∴ AB = √(AC² + BC² - 2AC·BC·cos C)
      = √(4² + 3² - 2×4×3×2/3) = 3，可得 A = C，
∴ B = π - 2C，
则 tan B = tan(π - 2C) = -tan 2C
         = (-2×√5/2) / (1 - 5/4) = 4√5。
故选：C。
```

### Span Audit

- `sp_q3_01`：题干分式，复核图见 [q3_stem_formula.png](/C:/Users/EDY/Documents/教研基建/tmp/manual_transcription_spans/q3_stem_formula.png)
- `sp_q3_02`：末段二倍角公式，复核图见 [q3_bottom_formula.png](/C:/Users/EDY/Documents/教研基建/tmp/manual_transcription_spans/q3_bottom_formula.png)
- 审查结论：首轮内容基本正确，二轮重点是把分式、根式和二倍角公式改成规范 LaTeX。

### Pass 2

```md
3.（2020·新课标Ⅲ）在 $\triangle ABC$ 中，$\cos C=\dfrac{2}{3}$，$AC=4$，$BC=3$，则 $\tan B=(\ \ )$。

A. $\sqrt{5}$

B. $2\sqrt{5}$

C. $4\sqrt{5}$

D. $8\sqrt{5}$

**答案**：C

**解析**：

因为

$$
\cos C=\frac{2}{3},\quad AC=4,\quad BC=3
$$

所以

$$
\tan C=\sqrt{\frac{1}{\cos^2 C}-1}
=\sqrt{\frac{1}{\left(\frac{2}{3}\right)^2}-1}
=\frac{\sqrt{5}}{2}
$$

又由余弦定理，

$$
AB=\sqrt{AC^2+BC^2-2AC\cdot BC\cdot \cos C}
$$

代入得

$$
AB=\sqrt{4^2+3^2-2\times 4\times 3\times \frac{2}{3}}=3
$$

故 $AB=BC$，从而 $A=C$。

于是

$$
B=\pi-2C
$$

所以

$$
\tan B=\tan(\pi-2C)=-\tan 2C
=\frac{-2\tan C}{1-\tan^2 C}
=\frac{-2\times \frac{\sqrt{5}}{2}}{1-\frac{5}{4}}
=4\sqrt{5}
$$

故选 C。
```

---

## 3. 高中数学 `tq_010`

题图：

- [tq_010_考点2：三角形形状判别及解的个数_例题讲解_Q2.png](/C:/Users/EDY/Documents/教研基建/outputs/ingress_splitter_v0.1/codex_profile_senior_math_transcription_v03_20260624/question_crops/tq_010_考点2：三角形形状判别及解的个数_例题讲解_Q2.png)

### Pass 1

```md
2. 在△ABC中，sin A = (sin B + sin C) / (cos B + cos C)，则△ABC的形状是（ ）

A. 等腰三角形
B. 直角三角形
C. 等腰直角三角形
D. 等腰或直角三角形

【解析】解：由 sin A = (sin B + sin C) / (cos B + cos C)，
整理得 sin A cos B + sin A cos C = sin B + sin C = sin(A + C) + sin(A + B)，
化简得 cos A sin C + cos A sin B = cos A (sin C + sin B) = 0，
由于 sin C + sin B > 0，
所以 cos A = 0，由于 A ∈ (0, π)，
所以 A = π/2。
所以△ABC为直角三角形。
故选：B。
```

### Span Audit

- `sp_q10_01`：题干分式结构
- `sp_q10_02`：`sin(A+C)+sin(A+B)` 的来源
- `sp_q10_03`：结论 `A=\pi/2`
- 审查结论：首轮逻辑与题图一致，二轮主要做 LaTeX 规范化。

### Pass 2

```md
2. 在 $\triangle ABC$ 中，

$$
\sin A=\frac{\sin B+\sin C}{\cos B+\cos C}
$$

则 $\triangle ABC$ 的形状是（ ）

A. 等腰三角形

B. 直角三角形

C. 等腰直角三角形

D. 等腰或直角三角形

**答案**：B

**解析**：

由

$$
\sin A=\frac{\sin B+\sin C}{\cos B+\cos C}
$$

可得

$$
\sin A\cos B+\sin A\cos C=\sin B+\sin C
$$

又因为

$$
\sin(A+B)=\sin A\cos B+\cos A\sin B
$$

$$
\sin(A+C)=\sin A\cos C+\cos A\sin C
$$

所以

$$
\sin(A+B)+\sin(A+C)
=\sin A\cos B+\sin A\cos C+\cos A(\sin B+\sin C)
$$

结合上式可化为

$$
\cos A(\sin B+\sin C)=0
$$

由于 $\sin B+\sin C>0$，故

$$
\cos A=0
$$

又因为 $A\in(0,\pi)$，所以

$$
A=\frac{\pi}{2}
$$

故 $\triangle ABC$ 为直角三角形。

故选 B。
```

---

## 4. 高中数学 `tq_018`

题图：

- [tq_018_考点3：三角形中的代数求值问题_例题讲解_Q1.png](/C:/Users/EDY/Documents/教研基建/outputs/ingress_splitter_v0.1/codex_profile_senior_math_transcription_v03_20260624/question_crops/tq_018_考点3：三角形中的代数求值问题_例题讲解_Q1.png)

### Pass 1

```md
1.（新课标Ⅰ）△ABC的内角 A，B，C 的对边分别为 a，b，c。已知 a sin A - b sin B = 4c sin C，cos A = -1/4，则 b/c =（ ）

A. 6
B. 5
C. 4
D. 3

【答案】A

【解析】解：∵ △ABC 的内角 A，B，C 的对边分别为 a，b，c，
a sin A - b sin B = 4c sin C，cos A = -1/4，
∴ 由正弦定理得：
{
 a² - b² = 4c²
 cos A = (b² + c² - a²)/(2bc) = -1/4
}
解得 3c² = 1/2 bc，
∴ b/c = 6。
故选：A。
```

### Span Audit

- `sp_q18_01`：题干 `-1/4`
- `sp_q18_02`：方程组花括号
- `sp_q18_03`：最终比例 `b/c = 6`
- 审查结论：首轮抄录正确，二轮把方程组改成标准展示公式。

### Pass 2

```md
1.（新课标Ⅰ）$\triangle ABC$ 的内角 $A,B,C$ 的对边分别为 $a,b,c$。已知

$$
a\sin A-b\sin B=4c\sin C,\quad \cos A=-\frac{1}{4}
$$

则 $\dfrac{b}{c}=(\ \ )$。

A. $6$

B. $5$

C. $4$

D. $3$

**答案**：A

**解析**：

由正弦定理，

$$
\frac{a}{\sin A}=\frac{b}{\sin B}=\frac{c}{\sin C}
$$

所以

$$
a\sin A-b\sin B=4c\sin C
\Longrightarrow a^2-b^2=4c^2
$$

又由余弦定理，

$$
\cos A=\frac{b^2+c^2-a^2}{2bc}=-\frac{1}{4}
$$

将 $a^2=b^2+4c^2$ 代入得

$$
\frac{b^2+c^2-(b^2+4c^2)}{2bc}=-\frac{1}{4}
$$

即

$$
\frac{-3c^2}{2bc}=-\frac{1}{4}
$$

解得

$$
\frac{b}{c}=6
$$

故选 A。
```

---

## 5. 高中数学 `tq_025`

题图：

- [tq_025_考点4：解三角形的最值范围问题_例题讲解_Q1.png](/C:/Users/EDY/Documents/教研基建/outputs/ingress_splitter_v0.1/codex_profile_senior_math_transcription_v03_20260624/question_crops/tq_025_考点4：解三角形的最值范围问题_例题讲解_Q1.png)

### Pass 1

```md
1. 在△ABC中，a，b，c 分别是角 A，B，C 的对边，且 cos 2B + 3cos(A + C) + 2 = 0，b = √3，那么△ABC 周长的最大值是（ ）

A. √3
B. 2√3
C. 3√3
D. 4√3

【解析】解：由 cos 2B + 3cos(A + C) + 2 = 0，A + B + C = π，
可得 2cos²B - 1 - 3cos B + 2 = 0，
即 (2cos B - 1)(cos B - 1) = 0，
∵ 0 < B < π，
∴ cos B = 1/2，则 B = π/3。
∵ b = √3，
正弦定理可得：a = b sin A / sin B，c = b sin C / sin B，
则 a + c = 2sin A + 2sin(2π/3 - A)
       = 2sin A + 2sin(2π/3)cos A - 2cos(2π/3)sin A
       = 3sin A + √3 cos A
       = 2√3 sin(A + π/6)，0 < A < 2π/3，
∴ π/6 < A + π/6 < 5π/6。
当 A + π/6 = π/2，即 A = π/3 时，a + c 取得最大值为 2√3。
那么△ABC 周长的最大值为：2√3 + √3 = 3√3。
故选：C。
```

### Span Audit

- `sp_q25_01`：`A+B+C=\pi` 推导到 `cos(A+C)=-cos B`
- `sp_q25_02`：`a+c` 的三角恒等变形
- `sp_q25_03`：最大值点 `A=\pi/3`
- 审查结论：首轮整体可读，二轮主要是公式版式规范化。

### Pass 2

```md
1. 在 $\triangle ABC$ 中，$a,b,c$ 分别是角 $A,B,C$ 的对边，且

$$
\cos 2B+3\cos(A+C)+2=0,\quad b=\sqrt{3}
$$

那么 $\triangle ABC$ 周长的最大值是（ ）

A. $\sqrt{3}$

B. $2\sqrt{3}$

C. $3\sqrt{3}$

D. $4\sqrt{3}$

**答案**：C

**解析**：

由 $A+B+C=\pi$，得

$$
A+C=\pi-B
$$

所以

$$
\cos(A+C)=\cos(\pi-B)=-\cos B
$$

代入原式得

$$
\cos 2B-3\cos B+2=0
$$

又因为

$$
\cos 2B=2\cos^2 B-1
$$

所以

$$
2\cos^2 B-1-3\cos B+2=0
$$

即

$$
(2\cos B-1)(\cos B-1)=0
$$

由于 $0<B<\pi$，故 $\cos B\neq 1$，所以

$$
\cos B=\frac{1}{2}\Rightarrow B=\frac{\pi}{3}
$$

由正弦定理，

$$
a=\frac{b\sin A}{\sin B},\quad c=\frac{b\sin C}{\sin B}
$$

又因为 $b=\sqrt{3},\ \sin B=\sin\frac{\pi}{3}=\frac{\sqrt{3}}{2}$，所以

$$
a=2\sin A,\quad c=2\sin C
$$

而

$$
C=\pi-A-B=\frac{2\pi}{3}-A
$$

故

$$
a+c=2\sin A+2\sin\left(\frac{2\pi}{3}-A\right)
$$

化简得

$$
a+c=3\sin A+\sqrt{3}\cos A
=2\sqrt{3}\sin\left(A+\frac{\pi}{6}\right)
$$

当

$$
A+\frac{\pi}{6}=\frac{\pi}{2}
$$

即

$$
A=\frac{\pi}{3}
$$

时，$a+c$ 取得最大值 $2\sqrt{3}$。

所以三角形周长最大值为

$$
a+b+c=2\sqrt{3}+\sqrt{3}=3\sqrt{3}
$$

故选 C。
```

---

## 6. 初中几何 `tq_002`

题图：

- [tq_002_考点1_倍长中线与中位线_强化训练_Q变式1-1.png](/C:/Users/EDY/Documents/教研基建/outputs/ingress_splitter_v0.1/codex_profile_junior_geometry_transcription_v02_20260624/question_crops/tq_002_考点1_倍长中线与中位线_强化训练_Q变式1-1.png)

### Pass 1

```md
【变式1-1】
（2024 秋·天门期末）

如图，AD 是△ABC 的边 BC 上的中线，若 AB = 5，AD = 3，则 AC 的取值范围为（ ）

A. 1 < AC < 11
B. 1 < AC < 8
C. 2 < AC < 8
D. 1 < AC < 4

【答案】A

【解析】解：延长 AD 到点 E，使 ED = AD，连接 EB。
∵ AD 是△ABC 的边 BC 上的中线，
∴ BD = CD。
在△EBD 和△ACD 中，
ED = AD，
∠EBD = ∠ADC，
BD = CD，
∴ △EBD ≌ △ACD（SAS），
∴ EB = AC。
∵ AB = 5，AD = 3，
∴ AE = 2AD = 6。
∵ AE - AB < EB < AE + AB，
且 AE - AB = 6 - 5 = 1，AE + AB = 6 + 5 = 11，
∴ 1 < AC < 11。
故选：A。
```

### Span Audit

- 复核选项块：[jq2_options_block.png](/C:/Users/EDY/Documents/教研基建/tmp/manual_transcription_spans/jq2_options_block.png)
- 复核答案边界：[jq2_answer_line.png](/C:/Users/EDY/Documents/教研基建/tmp/manual_transcription_spans/jq2_answer_line.png)
- 复核全等块：[jq2_congruence_block.png](/C:/Users/EDY/Documents/教研基建/tmp/manual_transcription_spans/jq2_congruence_block.png)
- 审查结论：首轮抄录正确，二轮主要做几何符号标准化。

### Pass 2

```md
## 变式 1-1

（2024 秋·天门期末）

如图，$AD$ 是 $\triangle ABC$ 的边 $BC$ 上的中线，若 $AB=5,\ AD=3$，则 $AC$ 的取值范围为（ ）

A. $1<AC<11$

B. $1<AC<8$

C. $2<AC<8$

D. $1<AC<4$

**答案**：A

**解析**：

延长 $AD$ 到点 $E$，使 $ED=AD$，连接 $EB$。

因为 $AD$ 是 $\triangle ABC$ 的边 $BC$ 上的中线，

所以

$$
BD=CD
$$

在 $\triangle EBD$ 和 $\triangle ACD$ 中，

$$
ED=AD,\quad \angle EBD=\angle ADC,\quad BD=CD
$$

所以

$$
\triangle EBD \cong \triangle ACD \quad (SAS)
$$

从而

$$
EB=AC
$$

又因为

$$
AE=2AD=6,\quad AB=5
$$

在 $\triangle ABE$ 中，由三角形三边关系得

$$
AE-AB<EB<AE+AB
$$

即

$$
6-5<EB<6+5
$$

所以

$$
1<EB<11
$$

又因为 $EB=AC$，故

$$
1<AC<11
$$

故选 A。
```

---

## 7. 初中几何 `tq_004`

题图：

- [tq_004_考点1_倍长中线与中位线_强化训练_Q变式2-1.png](/C:/Users/EDY/Documents/教研基建/outputs/ingress_splitter_v0.1/codex_profile_junior_geometry_transcription_v02_20260624/question_crops/tq_004_考点1_倍长中线与中位线_强化训练_Q变式2-1.png)

### Pass 1

```md
【变式2-1】
（2023 秋·黄埔区校级期中）

如图，已知△ABC中，AB = AC，CE 是 AB 边上的中线，延长 AB 到 D，使 BD = AB。

（1）若△ACE 的面积为 2，则△ACD 的面积为 ____；（直接写出答案）

（2）若 AC = 4，BC = 3，求△ACE 和△BCE 的周长之差；

（3）证明：CD = 2CE。

【答案】（1）8；
（2）1；
（3）证明过程见解答。

【分析】（3）取的中点 F，连接 BF，根据中点的性质可得到 AE = AF，再根据 SAS 判定△ABF ≌ △ACE，
由全等三角形的对应边相等可得到 BF = CE，再利用三角形中位线定理得到 DC = 2BF，即证得了 DC = 2CE。

【解答】
（1）解：∵ CE 是 AB 边上的中线，
∴ △ACE 的面积 = △BCE 的面积 = 2，
∵ BD = AB，
∴ △ABC 的面积 = △DBC 的面积 = 4，
∴ △ACD 的面积 = 2△ABC 的面积 = 8，
故答案为：8；

（2）解：∵ CE 是 AB 边上的中线，
∴ AE = BE，
∵ AC = 4，BC = 3，
∴ △ACE 和△BCE 的周长之差 = AC + CE + AE - (BC + CE + BE) = AC - BC = 1；

（3）证明：取 AC 的中点 F，连接 BF，
∵ AB = AC，点 E，F 分别是 AB，AC 的中点，
∴ AE = AF，
在△ABF 和△ACE 中，
AF = AE，
∠A = ∠A，
AB = AC，
∴ △ABF ≌ △ACE（SAS），
∴ BF = CE，
∵ BD = AB，AF = CF，
∴ DC = 2BF，
∴ DC = 2CE。
```

### Span Audit

- `sp_j4_01`：三问题目的字段拆分
- `sp_j4_02`：`△ABC` 与 `△DBC` 面积关系
- `sp_j4_03`：第三问中的 `AF=CF`
- 审查结论：首轮可读，二轮把分问结构和证明层次整理成规范 Markdown。

### Pass 2

```md
## 变式 2-1

（2023 秋·黄埔区校级期中）

如图，已知 $\triangle ABC$ 中，$AB=AC$，$CE$ 是 $AB$ 边上的中线，延长 $AB$ 到 $D$，使 $BD=AB$。

1. 若 $\triangle ACE$ 的面积为 $2$，则 $\triangle ACD$ 的面积为 ______；
2. 若 $AC=4,\ BC=3$，求 $\triangle ACE$ 和 $\triangle BCE$ 的周长之差；
3. 证明：$CD=2CE$。

**答案**：

1. $8$
2. $1$
3. 证明见解析

**解析**：

### （1）

因为 $CE$ 是 $AB$ 边上的中线，

所以

$$
S_{\triangle ACE}=S_{\triangle BCE}=2
$$

故

$$
S_{\triangle ABC}=4
$$

又因为 $BD=AB$，可得

$$
S_{\triangle DBC}=S_{\triangle ABC}=4
$$

所以

$$
S_{\triangle ACD}=S_{\triangle ABC}+S_{\triangle DBC}=8
$$

### （2）

因为 $CE$ 是 $AB$ 边上的中线，

所以

$$
AE=BE
$$

故两三角形周长之差为

$$
(AC+CE+AE)-(BC+CE+BE)=AC-BC=1
$$

### （3）

取 $AC$ 的中点 $F$，连接 $BF$。

因为 $AB=AC$，且 $E,F$ 分别是 $AB,AC$ 的中点，

所以

$$
AE=AF
$$

在 $\triangle ABF$ 和 $\triangle ACE$ 中，

$$
AF=AE,\quad \angle A=\angle A,\quad AB=AC
$$

所以

$$
\triangle ABF \cong \triangle ACE \quad (SAS)
$$

从而

$$
BF=CE
$$

又因为 $BD=AB$，且 $F$ 是 $AC$ 的中点，

所以可推出

$$
DC=2BF
$$

于是

$$
DC=2CE
$$
```

---

## 8. 初中几何 `tq_009`

题图：

- [tq_009_考点3_利用平行线+中点构造全等_例题讲解_Q例5.png](/C:/Users/EDY/Documents/教研基建/outputs/ingress_splitter_v0.1/codex_profile_junior_geometry_transcription_v02_20260624/question_crops/tq_009_考点3_利用平行线+中点构造全等_例题讲解_Q例5.png)

### Pass 1

```md
【例5】

如图，已知梯形 ABCD 中，CD // AB，M 为腰 AD 上的一点，若 AB + CD = BC，MC 平分∠DCB，求证：BM ⟂ MC。

【解答】证明：延长 CM，BA，交于点 E，
∵ MC 平分∠DCB，
∴ ∠1 = ∠2，
∵ BA // CD，
∴ ∠E = ∠2，
∴ ∠E = ∠2 = ∠1，
∴ BE = BC。
∵ AB + CD = BC，
∴ DC = AE。
在△AME 和△DMC 中，
∠DMC = ∠AME，
∠1 = ∠E，
CD = EA，
∴ △AME ≌ △DMC（AAS），
∴ CM = EM，BM 是 EC 中线（等腰三角形三线合一），
∴ BM ⟂ MC。
```

### Span Audit

- `sp_j9_01`：`∠1 = ∠2` 与平行线角关系
- `sp_j9_02`：`DC = AE`
- `sp_j9_03`：`BM 是 EC 中线（等腰三角形三线合一）`
- 审查结论：首轮逻辑完整，二轮主要做公式与证明结构规整。

### Pass 2

```md
## 例 5

如图，已知梯形 $ABCD$ 中，$CD\parallel AB$，$M$ 为腰 $AD$ 上的一点，若 $AB+CD=BC$，$MC$ 平分 $\angle DCB$，求证：$BM\perp MC$。

**解析**：

延长 $CM$ 与 $BA$，交于点 $E$。

因为 $MC$ 平分 $\angle DCB$，

所以

$$
\angle 1=\angle 2
$$

又因为 $BA\parallel CD$，

所以

$$
\angle E=\angle 2
$$

从而

$$
\angle E=\angle 1
$$

于是

$$
BE=BC
$$

又因为

$$
AB+CD=BC
$$

所以

$$
AE=BE-AB=BC-AB=CD
$$

在 $\triangle AME$ 和 $\triangle DMC$ 中，

$$
\angle DMC=\angle AME,\quad \angle E=\angle 1,\quad AE=CD
$$

所以

$$
\triangle AME \cong \triangle DMC \quad (AAS)
$$

从而

$$
EM=CM
$$

因为 $E,C,M$ 构成等腰三角形，且 $B$ 在底边 $EC$ 上，$BM$ 为中线，

所以

$$
BM\perp MC
$$
```

---

## 9. 初中几何 `tq_021`

题图：

- [tq_021_考点3_利用平行线+中点构造全等_例题讲解_Q例9.png](/C:/Users/EDY/Documents/教研基建/outputs/ingress_splitter_v0.1/codex_profile_junior_geometry_transcription_v02_20260624/question_crops/tq_021_考点3_利用平行线+中点构造全等_例题讲解_Q例9.png)

### Pass 1

```md
【例9】

在四边形 ABCD 中，AB = BC，∠ABC = ∠ADB = ∠BDC = 60°，求证：DA + DC = DB。

【解答】证明：如图，将△BDC 绕点 B 旋转 60° 得到△BHA，
∴ △ABH ≌ △CBD，
∴ BD = BH，∠ABH = ∠CBD，∠BCD = ∠BAH，DC = AH，
∵ ∠ABC = ∠ADB = ∠BDC = 60°，
∴ ∠BAD + ∠BCD = 180°，
∴ ∠BAD + ∠BAH = 180°，
∴ 点 A，点 H，点 D 三点共线，
∵ ∠ABD + ∠CBD = ∠ABC = 60°，
∴ ∠ABH + ∠ABD = 60° = ∠DBH，
又∵ ∠ADB = 60°，
∴ △BDH 是等边三角形，
∴ DH = BD，
∵ BD = DH = AD + AH = AD + DC，
∴ DA + DC = DB。
```

### Span Audit

- `sp_j21_01`：旋转后对应三角形名称
- `sp_j21_02`：A、H、D 共线的推理
- `sp_j21_03`：`DH = AD + AH`
- 审查结论：首轮逻辑成立，二轮主要规范证明层级。

### Pass 2

```md
## 例 9

在四边形 $ABCD$ 中，$AB=BC$，$\angle ABC=\angle ADB=\angle BDC=60^\circ$。求证：$DA+DC=DB$。

**解析**：

如图，将 $\triangle BDC$ 绕点 $B$ 旋转 $60^\circ$，得到 $\triangle BHA$。

则有

$$
\triangle ABH \cong \triangle CBD
$$

所以

$$
BH=BD,\quad AH=DC,\quad \angle ABH=\angle CBD,\quad \angle BAH=\angle BCD
$$

又因为

$$
\angle ABC=60^\circ,\quad \angle ADB=60^\circ,\quad \angle BDC=60^\circ
$$

所以

$$
\angle BAD+\angle BCD=180^\circ
$$

而 $\angle BAH=\angle BCD$，故

$$
\angle BAD+\angle BAH=180^\circ
$$

于是点 $A,H,D$ 三点共线。

又因为

$$
\angle ABD+\angle CBD=\angle ABC=60^\circ
$$

且 $\angle ABH=\angle CBD$，故

$$
\angle ABH+\angle ABD=60^\circ
$$

即

$$
\angle DBH=60^\circ
$$

结合 $\angle ADB=60^\circ$ 且 $A,H,D$ 共线，可知

$$
\angle BDH=60^\circ
$$

故 $\triangle BDH$ 为等边三角形，

所以

$$
DH=DB
$$

又因为 $A,H,D$ 三点共线，且 $AH=DC$，故

$$
DH=DA+AH=DA+DC
$$

从而

$$
DA+DC=DB
$$
```

---

## 10. 初中几何 `tq_030`

题图：

- [tq_030_考点3_利用平行线+中点构造全等_课后落实_Q课后1.png](/C:/Users/EDY/Documents/教研基建/outputs/ingress_splitter_v0.1/codex_profile_junior_geometry_transcription_v02_20260624/question_crops/tq_030_考点3_利用平行线+中点构造全等_课后落实_Q课后1.png)

### Pass 1

```md
课后练习 1

（2025 春·杭州期末）

在△ABC中，AD 是 BC 边上的中线，若 AB = 5，AD = 8，则 AC 的取值范围是（ ）

A. 16 < AC < 20
B. 11 < AC < 21
C. 16 < AC < 21
D. 11 < AC < 20

【答案】B

【解答】解：在△ABC中，AD 是 BC 边上的中线，若 AB = 5，AD = 8，如图，延长 AD 至点 E，使 DE = AD = 8，
∴ AE = 16，
∵ AD 为 BC 边上的中线，
∴ BD = CD，
在△ADC 和△EDB 中，
CD = BD，
∠ADC = ∠EDB，
AD = DE，
∴ △ADC ≌ △EDB（SAS），
∴ BE = AC，
∵ AE - AB < BE < AE + AB，
∴ 16 - 5 < BE < 16 + 5，
即 11 < BE < 21，
∴ 11 < AC < 21。
故选：B。
```

### Span Audit

- `sp_j30_01`：题干选项
- `sp_j30_02`：`△ADC ≌ △EDB`
- `sp_j30_03`：最后一步 `BE = AC`
- 审查结论：首轮正确，二轮做标准化表达。

### Pass 2

```md
## 课后练习 1

（2025 春·杭州期末）

在 $\triangle ABC$ 中，$AD$ 是 $BC$ 边上的中线，若 $AB=5,\ AD=8$，则 $AC$ 的取值范围是（ ）

A. $16<AC<20$

B. $11<AC<21$

C. $16<AC<21$

D. $11<AC<20$

**答案**：B

**解析**：

延长 $AD$ 至点 $E$，使 $DE=AD=8$，则

$$
AE=16
$$

又因为 $AD$ 为 $BC$ 边上的中线，所以

$$
BD=CD
$$

在 $\triangle ADC$ 和 $\triangle EDB$ 中，

$$
CD=BD,\quad \angle ADC=\angle EDB,\quad AD=DE
$$

所以

$$
\triangle ADC \cong \triangle EDB \quad (SAS)
$$

从而

$$
BE=AC
$$

在 $\triangle ABE$ 中，由三角形三边关系，

$$
AE-AB<BE<AE+AB
$$

代入得

$$
16-5<BE<16+5
$$

即

$$
11<BE<21
$$

又因为 $BE=AC$，故

$$
11<AC<21
$$

故选 B。
```

---

## 审查结论

1. 这 10 题的 `Pass 1` 都是人工对着题图直接抄录，不依赖现有 runtime 的错误文本。
2. `Pass 2` 只做两类动作：
   - suspect span 精修
   - Markdown 与 LaTeX 规范化
3. 从这 10 题看，旗舰模型人工流程可以产出比现有 runtime 明显更可靠的结果。
4. 但它仍然不是“自动化批量方案”；如果要产品化，必须把 `Pass 1 + Span Audit + Pass 2` 结构固化成可执行 pipeline。
