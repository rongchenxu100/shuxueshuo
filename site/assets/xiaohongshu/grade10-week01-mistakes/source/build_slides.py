"""Deterministic SVG authoring. Run from any directory; math stays in this source."""
from pathlib import Path
from html import escape
import json
import math
import re

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
INK = '#123d43'
TEAL = '#087e77'
RED = '#c54f44'
MUTED = '#5b6b70'
PAPER = '#fffdf7'
MINT = '#e9f3ef'
BLUSH = '#fbefea'
AMBER = '#af7829'
slides = []
buf = []

def raw(s): buf.append(s)
def text(x,y,s,size=32,color=INK,weight=400,anchor='start'):
    content=escape(s).replace('∁ᵤ', '∁<tspan baseline-shift="sub" font-size="70%">U</tspan>')
    raw(f'<text xml:space="preserve" x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{content}</text>')
def lines(x,y,ss,size=32,gap=48,color=INK,weight=400):
    for i,s in enumerate(ss): text(x,y+i*gap,s,size,color,weight)
def box(x,y,w,h,fill=PAPER,stroke='#ccdcd5',r=24):
    raw(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
def line(x1,y1,x2,y2,color=TEAL,width=4,dash=None):
    raw(f'<path d="M{x1} {y1} L{x2} {y2}" fill="none" stroke="{color}" stroke-width="{width}"'+(f' stroke-dasharray="{dash}"' if dash else '')+'/>')
def arrow(x1,y1,x2,y2,color=TEAL):
    line(x1,y1,x2,y2,color)
    a=math.atan2(y2-y1,x2-x1)
    pts=[(x2,y2),(x2-15*math.cos(a-.48),y2-15*math.sin(a-.48)),(x2-15*math.cos(a+.48),y2-15*math.sin(a+.48))]
    raw('<polygon points="'+' '.join(f'{x:.2f},{y:.2f}' for x,y in pts)+f'" fill="{color}"/>')
def dot(x,y,closed=False,color=TEAL,r=8):
    raw(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color if closed else PAPER}" stroke="{color}" stroke-width="3"/>')
def begin(name,title,source,category):
    global buf
    buf=[]
    raw('<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1440" viewBox="0 0 1080 1440">')
    raw('<style>text{font-family:"PingFang SC","Hiragino Sans GB","Arial Unicode MS",sans-serif}path{stroke-linecap:round;stroke-linejoin:round}</style>')
    raw('<defs><pattern id="grid" width="36" height="36" patternUnits="userSpaceOnUse"><path d="M36 0H0V36" fill="none" stroke="#247f76" stroke-opacity=".04" stroke-width="1"/></pattern></defs>')
    raw(f'<rect width="1080" height="1440" fill="{PAPER}"/><rect width="1080" height="1440" fill="url(#grid)"/>')
    text(72,92,'数学说  /  高一第一周错题复盘',26,TEAL,600)
    text(1008,92,f'{len(slides)+1:02d} / 09',26,MUTED,400,'end')
    lines(72,164,title,48,58,INK,700)
    if source:text(72,269,source,25,MUTED)
    line(72,1340,1008,1340,'#d7e1d9',2)
    text(72,1384,'每类一道代表题 · 集合与常用逻辑用语',24,MUTED)
    text(1008,1384,'数学说',26,TEAL,700,'end')
    slides.append({'png':name+'.png','mode':'svg','source':name+'.svg','category':category,'problem':source})
def end():
    raw('</svg>')
    (HERE/slides[-1]['source']).write_text('\n'.join(buf),encoding='utf-8')
def original(y,ss):
    box(72,y,936,60+42*(len(ss)-1),BLUSH,'#efd5cb',16)
    lines(96,y+40,ss,29,42,RED)
def takeaway(ss,y=1192):
    box(72,y,936,116,MINT,'#c9ddd3',20)
    text(96,y+38,'带走这个方法',25,TEAL,700)
    lines(96,y+80,ss,30,40,INK,600)
def answer(y,s):
    box(72,y,936,78,INK,INK,18)
    text(96,y+49,'正确结论',26,'#9ed5c5',600)
    text(976,y+51,s,38,PAPER,700,'end')
def nline(x,y,w,domain,intervals,label,ticks,color=TEAL):
    lo,hi=domain
    scale=lambda v:x+(v-lo)/(hi-lo)*w
    line(x,y,x+w,y,'#b6c4c2',2)
    text(x-28,y+10,label,29,INK,600,'end')
    for l,r,lc,rc in intervals:
        lx=x if l is None else scale(l)
        rx=x+w if r is None else scale(r)
        line(lx,y,rx,y,color,7)
        if l is None:arrow(x+19,y,x,y,color)
        else:dot(lx,y,lc,color)
        if r is None:arrow(x+w-19,y,x+w,y,color)
        else:dot(rx,y,rc,color)
    for v,l in ticks: text(scale(v),y+45,l,26,MUTED,400,'middle')

# 01 — Parent's weekly notebook; counts come from the original book, not slides.
begin('01-cover',[], '', 'cover')
buf=buf[:3]  # Keep SVG, typography and grid definitions; replace the course header.
raw('<rect width="1080" height="1440" fill="#f7f0df"/><rect width="1080" height="1440" fill="url(#grid)"/>')
raw('<path d="M78 70L487 54L492 109L80 120Z" fill="#e4cfa0" opacity=".58"/>')
text(100,98,'陪孩子一起复盘 · 开学记录',29,'#7a664c',500)
text(84,198,'高一第一周',70,INK,700)
text(84,292,'荣同学的错题本',84,INK,700)
raw('<path d="M88 314 Q345 331 675 315" fill="none" stroke="#c69b56" stroke-width="5"/>')
text(86,363,'8种错误类型，每类选1题分享',33,TEAL,600)
js=(HERE.parents[2]/'js/mistake-book.js').read_text()
keys=['degree','elements','boundary','venn','universal','empty','conditions','understanding']
cover_data=[]
for key in keys:
    match=re.search(r"key: '"+key+r"', title: '([^']+)',\s*cards: \[([^]]+)\]",js)
    assert match, key
    cover_data.append((match[1],len(re.findall(r"'[^']+'",match[2]))))
total=sum(n for _,n in cover_data)
assert len(cover_data)==8 and total==17
box(64,398,952,819,'#fffdf8','#dfd6c4',18)
text(94,443,f'这8类在原错题本中的分布 · 共{total}题',29,'#786f5f',500)
for i,(label,n) in enumerate(cover_data):
    y=494+i*88
    text(94,y,f'{i+1:02d}',26,'#aa946e',600)
    text(143,y,label,29,INK,600)
    raw(f'<rect x="143" y="{y+16}" width="708" height="16" rx="8" fill="#f0ede4"/>')
    raw(f'<rect x="143" y="{y+16}" width="{n/3*708}" height="16" rx="8" fill="{["#81ada0","#8badb1","#c4a166"][n-1]}"/>')
    text(931,y+35,f'{n}题',28,TEAL,600,'end')
text(94,1190,'每条柱长代表题数；后面每类只放一道代表题。',25,'#786f5f')
text(86,1294,'荣同学，加油。我们一起慢慢来。',40,INK,600)
text(86,1354,'把不会的，一点点变成会的。',30,'#827460')
raw('<path d="M937 1266L944 1288L967 1289L949 1303L955 1326L936 1312L917 1326L923 1303L905 1289L930 1288Z" fill="#e5c585" stroke="#ba9557" stroke-width="2"/>')
slides[-1]['distribution']=[{'title':title,'count':n} for title,n in cover_data]
slides[-1]['distributionScope']='本次选中的8类在原错题本中共17题；每类分享1题。'
end()

# 02 — Degree. Two roots require nonzero leading coefficient and Δ>0.
assert 4*4-4*.5*4>0
begin('02-degree',['检查二次项系数','是否为0'],'特训一 · 第9题','degree')
box(72,290,936,152)
lines(96,337,['集合 A={x｜kx²+4x+4=0} 中有2个元素，','求实数 k 的取值范围。'],34,54)
original(466,['原解：Δ=16−16k>0 → k<1'])
text(540,584,'用判别式前，先检查 k',38,INK,700,'middle')
arrow(540,604,540,639)
line(306,640,774,640);arrow(306,640,306,672);arrow(774,640,774,672)
for x,title,col,ss in [(72,'k=0',RED,['4x+4=0','x=−1，只有1个根','不满足“2个元素”']), (550,'k≠0',TEAL,['仍是一元二次方程','Δ=16−16k>0','得到 k<1'])]:
    box(x,690,458,298,BLUSH if col==RED else MINT,'#dddcd2')
    text(x+28,750,title,46,col,700)
    lines(x+28,815,ss,32,59)
answer(1056,'k∈(−∞,0)∪(0,1)')
takeaway(['系数为0时，先按剩余方程讨论。'])
end()

# 03 — Elements. Curves generated from y=x²−4, with shared transforms.
begin('03-elements',['描述法表示集合','先看集合元素是什么'],'特训二 · 第7题','elements')
box(72,290,936,234)
lines(96,337,['A={x｜y=x²−4}，B={y｜y=x²−4}，','C={(x,y)｜y=x²−4}。正确关系是：'],31,48)
text(96,447,'A. A=B      B. B⊆A',30);text(96,496,'C. A⊆C     D. 2∈C',30)
original(548,['原答案：A（判断 A=B）'])
text(72,659,'同一个条件，收集的对象不同',34,TEAL,700)
for i,(label,what,result) in enumerate([('x','横坐标','A=ℝ'),('y','纵坐标','B=[−4,+∞)'),('(x,y)','平面上的点','C 是点集')]):
    x=72+i*318
    box(x,688,300,350,MINT if i<2 else PAPER)
    text(x+150,747,label,44,TEAL,700,'middle');text(x+150,793,what,28,INK,400,'middle')
    if i==0:
        arrow(x+35,890,x+265,890);arrow(x+60,890,x+35,890)
        text(x+150,945,'任意实数',28,MUTED,400,'middle')
    elif i==1:
        nline(x+33,890,232,(-6,5),[(-4,None,True,False)],'', [(-4,'−4')])
    else:
        sx=lambda a:x+150+a*36
        sy=lambda b:900-b*16
        arrow(sx(-2.9),sy(0),sx(2.9),sy(0),'#8a9c9a')
        arrow(sx(0),sy(-4.5),sx(0),sy(4),'#8a9c9a')
        pts=[(sx(a),sy(a*a-4)) for a in [j/50 for j in range(-135,136)]]
        raw('<polyline points="'+' '.join(f'{a:.1f},{b:.1f}' for a,b in pts)+f'" fill="none" stroke="{TEAL}" stroke-width="4"/>')
        text(sx(0)-10,sy(0)-10,'O',21,MUTED,400,'end')
    text(x+150,1011,result,30,INK,600,'middle')
answer(1080,'B：B⊆A')
takeaway(['先看竖线前的元素，再读竖线后的条件。'])
end()

# 04 — Boundary. m=−1 gives B=(−3,0) subset [-3,4].
m=-1
assert 2*m-1==-3 and m+1==0
begin('04-boundary',['边界值一定要代入','原集合验证关系'],'特训三 · 第14题第2问','boundary')
box(72,290,936,156)
lines(96,336,['A=[−3,4]，B={x｜2m−1<x<m+1}。','若 A∪B=A，求 m 的取值范围。'],33,54)
original(468,['原解已分空集／非空集，得到 m>−1。','问题在于：边界 m=−1 能不能取？'])
box(72,594,936,344,MINT)
text(96,648,'代入 m=−1',40,TEAL,700)
nline(202,721,704,(-4,5),[(-3,4,True,True)],'A',[(-3,'−3'),(4,'4')])
nline(202,824,704,(-4,5),[(-3,0,False,False)],'B',[(-3,'−3'),(0,'0')])
text(96,914,'B=(−3,0) 中的每个数仍在 A 内。',31,INK,600)
lines(96,992,['B=∅：m≥2；B≠∅：−1≤m<2。'],31)
answer(1056,'m≥−1')
takeaway(['开端点，也可能允许参数取等。'])
end()

# 05 — Venn: U is exactly the union of two disks in this schematic.
begin('05-venn',['集合关系要画维恩图'],'特训四 · 第7题（多选）','venn')
box(72,290,936,254)
lines(96,333,['当 U 为全集，下列说法中正确的是：','A. A∩B=∅ ⇒ (∁ᵤA)∪(∁ᵤB)=U','B. A∩B=∅ ⇒ A=∅ 或 B=∅','C. A∪B=U ⇒ (∁ᵤA)∩(∁ᵤB)=∅','D. A∪B=∅ ⇒ A=B=∅'],29,45)
original(564,['原答案：AD。漏掉了 C 项。'])
text(72,674,'看 C：A∪B=U，全集就是两圆的并集',32,TEAL,700)
for i,title in enumerate(['① 取 A 的补集','② 取 B 的补集','③ 取二者交集']):
    x=72+i*318;box(x,702,300,268,PAPER)
    text(x+150,747,title,27,INK,600,'middle')
    cx=x+119;cy=844;d=64;r=68
    raw(f'<defs><mask id="exclude-{i}"><rect x="{x}" y="760" width="300" height="180" fill="white"/><circle cx="{cx if i==0 else cx+d}" cy="{cy}" r="{r}" fill="black"/></mask></defs>')
    for c in [cx,cx+d]:raw(f'<circle cx="{c}" cy="{cy}" r="{r}" fill="{MINT}"/>')
    if i<2:raw(f'<circle cx="{cx+d if i==0 else cx}" cy="{cy}" r="{r}" fill="#68b9a5" mask="url(#exclude-{i})"/>')
    for c in [cx,cx+d]:raw(f'<circle cx="{c}" cy="{cy}" r="{r}" fill="none" stroke="{TEAL}" stroke-width="3"/>')
    text(cx-21,cy+9,'A',29,INK,600,'middle');text(cx+d+21,cy+9,'B',29,INK,600,'middle')
    text(x+150,944,['B 中、A 外','A 中、B 外','无公共元素：∅'][i],27,TEAL,600,'middle')
lines(96,1015,['A项：无重叠，每个元素至少在一个补集中。','B项反例：A={1}，B={2}，两者均非空。','D项：并集为空，两个集合都只能为空。'],28,42)
answer(1144,'ACD')
text(96,1280,'先分别标区域，再做交、并、补运算。',33,TEAL,700)
end()

# 06 — Forall: all three pairs vs one counterexample. Original answer was correct.
assert 3**9>9 and 9**3>9 and (.25)**.5==.5
begin('06-universal',['“任意”指所有对象','都要满足条件'],'特训一 · 第15题第1问','universal')
box(72,290,936,222)
lines(96,332,['S 为至少含2个正实数的有限集。任意不同的','a,b∈S，若 aᵇ、bᵃ 至少一个属于 S，称为','“好集”，否则为“坏集”。判断：','A={1,3,9}，B={1,1/2,1/4}。'],30,48)
original(532,['原解：A 找到反例；B 只检查了 1/2、1/4。','原结论对，但证明 B 为好集还不完整。'])
for x,title,col in [(72,'好集：每一对都满足',TEAL),(550,'坏集：一对反例即可',RED)]:
    box(x,672,458,410,MINT if col==TEAL else BLUSH)
    text(x+25,724,title,30,col,700)
for j,(pair,proof) in enumerate([('1 与 1/2','1¹ᐟ²=1∈B'),('1 与 1/4','1¹ᐟ⁴=1∈B'),('1/2 与 1/4','(1/4)¹ᐟ²=1/2∈B')]):
    y=749+j*92
    box(96,y,410,80,PAPER,'#c9ddd3',12)
    text(112,y+31,pair,26,TEAL,600)
    text(112,y+66,proof,27,INK)
    text(480,y+50,'✓',37,TEAL,700,'middle')
text(300,1049,'全部通过 ✓',34,TEAL,700,'middle')
lines(578,788,['检查 A 中的 3、9：','3⁹>9，所以 3⁹∉A','9³>9，所以 9³∉A','这一对的两个幂','都不属于 A。'],28,49)
text(779,1049,'一对就能否定 ✕',31,RED,700,'middle')
answer(1104,'A 是坏集，B 是好集')
takeaway(['成立要覆盖全部；否定只需一个反例。'])
end()

# 07 — Empty-set branch. Closed interval degenerates to singleton when a=0.
begin('07-empty',['讨论集合包含关系','不能忘记空集'],'特训二 · 第5题','empty')
box(72,290,936,209)
lines(96,334,['A=[−1,1]，B={x｜a−1≤x≤2a−1}。','若 B⊆A，a 的取值范围是：','A. a≤1     B. a<1     C. 0≤a≤1     D. 0<a<1'],30,61)
original(522,['原解：−1≤a−1≤2a−1≤1，选 C。'])
text(540,630,'B⊆A，先问 B 有没有元素',36,INK,700,'middle')
arrow(540,650,540,680);line(306,680,774,680);arrow(306,680,306,710);arrow(774,680,774,710)
for x,title,col,ss in [(72,'B=∅',RED,['a−1>2a−1','得到 a<0','∅⊆A，全部保留']), (550,'B≠∅',TEAL,['a≥0，再比较端点','a−1≥−1，2a−1≤1','得到 0≤a≤1'])]:
    box(x,730,458,295,BLUSH if col==RED else MINT)
    text(x+28,794,title,43,col,700);lines(x+28,854,ss,30,62)
answer(1080,'A：a≤1')
takeaway(['空集分支的参数，也要并入最终答案。'])
end()

# 08 — Necessary: q => p. Boundary sample derived using a=-9.
a=-9
assert 1+a==-8 and 1-a==10 and a<=-3
begin('08-conditions',['充分、必要条件','要转成集合包含关系'],'特训五 · 第9题','conditions')
box(72,290,936,207)
lines(96,336,['p：x<−2 或 x>10，','q：x<1+a 或 x>1−a（a<0）。','若 p 是 q 的必要条件，求 a 的范围。'],32,58)
original(520,['原答案：a<0，只保留了题目给定的限制。'])
box(72,609,936,106,MINT)
text(540,652,'p 是 q 的必要条件',32,TEAL,700,'middle')
text(540,697,'q ⇒ p  ⇔  Q⊆P',36,INK,700,'middle')
lines(96,775,['左段包含：1+a≤−2  →  a≤−3','右段包含：1−a≥10  →  a≤−9'],34,58)
text(96,900,'代入 a=−9 验证：Q 的每个元素都在 P 内',29,MUTED)
nline(191,951,726,(-12,14),[(None,-2,False,False),(10,None,False,False)],'P',[(-2,'−2'),(10,'10')],MUTED)
nline(191,1054,726,(-12,14),[(None,-8,False,False),(10,None,False,False)],'Q',[(-8,'−8'),(10,'10')])
answer(1124,'a≤−9')
text(96,1280,'必要条件：从 q 推出 p，别把方向写反。',32,TEAL,700)
end()

# 09 — Same selected problem, deliberately unanswered. Graph is a reading aid.
begin('09-understanding-self-test',['先理解条件的含义，再明确','题目要求的推导方向'],'特训五 · 第11题 · 最后一题自己判断','understanding')
box(72,290,936,207)
lines(96,335,['若 −1≤x<2，则“x²−a≤0”为真命题的','一个充分条件可以是：'],32,48)
text(96,463,'A. a≥3     B. a>4     C. a≥1     D. a>1',31)
original(518,['原答案：C。读清两层含义，再重新选择。'])
box(72,610,454,161,MINT);box(550,610,458,161,BLUSH)
text(98,657,'“一个充分条件”',32,TEAL,700)
lines(98,710,['所选条件一成立，','原命题就一定成立。'],29,41)
text(576,657,'“命题为真”',32,RED,700)
lines(576,710,['范围内每一个 x，','都要满足 x²≤a。'],29,41)
arrow(301,786,540,824);arrow(779,786,540,824)
text(540,883,'真正要保证：a 能盖住所有这些 x²',34,INK,700,'middle')
sx=lambda x:274+(x+1.5)/4*530
sy=lambda y:1174-y*52
arrow(sx(-1.5),sy(0),sx(2.5),sy(0),'#879b98')
arrow(sx(0),sy(-.15),sx(0),sy(4.6),'#879b98')
pts=[(sx(-1+3*i/150),sy((-1+3*i/150)**2)) for i in range(151)]
raw('<polyline points="'+' '.join(f'{x:.2f},{y:.2f}' for x,y in pts)+f'" fill="none" stroke="{TEAL}" stroke-width="5"/>')
dot(sx(-1),sy(1),True);dot(sx(2),sy(4),False)
line(sx(0),sy(4),sx(2),sy(4),'#97b6aa',2,'7 7')
for x,l in [(-1,'−1'),(2,'2')]:text(sx(x),sy(0)+39,l,25,MUTED,400,'middle')
text(sx(0)-16,sy(4)+8,'4',25,MUTED,400,'end')
text(sx(0)-13,sy(0)+28,'O',23,MUTED,400,'end')
text(sx(2.5)+16,sy(0)+10,'x',27,MUTED)
text(sx(0)+19,sy(4.5),'y=x²',26,TEAL,600)
text(1000,1051,'接近2时，',28,INK,400,'end');text(1000,1091,'x²会怎样？',28,INK,400,'end')
text(72,1264,'先写下选项，并解释它为什么足够。',32,INK,700)
text(72,1310,'访问 shuxueshuo.com · 继续练习充分与必要条件',27,TEAL,600)
end()

manifest={'postType':'解题方法型','audience':'高一第一周','scope':'8个错误类型，每类一道题；封面+8页。排除cases、duplicates。','dimensions':[1080,1440],'slides':slides,'withheldAnswerSlides':['09-understanding-self-test.png']}
(HERE/'slide-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(f'Built {len(slides)} SVG slides')
