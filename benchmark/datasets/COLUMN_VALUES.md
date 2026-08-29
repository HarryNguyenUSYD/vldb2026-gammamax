# Benchmark dataset columns

Domains are inferred from current clean CSV files. Empty string and literal `?` are always invalid and excluded from every oracle. Closed lists contain remaining observed categorical values; numeric ranges contain observed extrema. No generated regex accepts every string.

## adult_20

48842 rows; 15 columns.

- **age** — Census Income column age; integer: range 17 to 90; distinct=74; missing=0.
- **workclass** — Census Income column workclass; list: Federal-gov; Local-gov; Never-worked; Private; Self-emp-inc; Self-emp-not-inc; State-gov; Without-pay; distinct=10; missing=963.
- **fnlwgt** — Census Income column fnlwgt; integer: range 12285 to 1490400; distinct=28523; missing=0.
- **education** — Census Income column education; list: 10th; 11th; 12th; 1st-4th; 5th-6th; 7th-8th; 9th; Assoc-acdm; Assoc-voc; Bachelors; Doctorate; HS-grad; Masters; Preschool; Prof-school; Some-college; distinct=16; missing=0.
- **education-num** — Census Income column education-num; integer: range 1 to 16; distinct=16; missing=0.
- **marital-status** — Census Income column marital-status; list: Divorced; Married-AF-spouse; Married-civ-spouse; Married-spouse-absent; Never-married; Separated; Widowed; distinct=7; missing=0.
- **occupation** — Census Income column occupation; list: Adm-clerical; Armed-Forces; Craft-repair; Exec-managerial; Farming-fishing; Handlers-cleaners; Machine-op-inspct; Other-service; Priv-house-serv; Prof-specialty; Protective-serv; Sales; Tech-support; Transport-moving; distinct=16; missing=966.
- **relationship** — Census Income column relationship; list: Husband; Not-in-family; Other-relative; Own-child; Unmarried; Wife; distinct=6; missing=0.
- **race** — Census Income column race; list: Amer-Indian-Eskimo; Asian-Pac-Islander; Black; Other; White; distinct=5; missing=0.
- **sex** — Census Income column sex; list: Female; Male; distinct=2; missing=0.
- **capital-gain** — Census Income column capital-gain; integer: range 0 to 99999; distinct=123; missing=0.
- **capital-loss** — Census Income column capital-loss; integer: range 0 to 4356; distinct=99; missing=0.
- **hours-per-week** — Census Income column hours-per-week; integer: range 1 to 99; distinct=96; missing=0.
- **native-country** — Census Income column native-country; list: Cambodia; Canada; China; Columbia; Cuba; Dominican-Republic; Ecuador; El-Salvador; England; France; Germany; Greece; Guatemala; Haiti; Holand-Netherlands; Honduras; Hong; Hungary; India; Iran; Ireland; Italy; Jamaica; Japan; Laos; Mexico; Nicaragua; Outlying-US(Guam-USVI-etc); Peru; Philippines; Poland; Portugal; Puerto-Rico; Scotland; South; Taiwan; Thailand; Trinadad&Tobago; United-States; Vietnam; Yugoslavia; distinct=43; missing=274.
- **income** — Census Income column income; list: <=50K; <=50K.; >50K; >50K.; distinct=4; missing=0.

## bank_marketing_222

45211 rows; 17 columns.

- **age** — Bank Marketing column age; integer: range 18 to 95; distinct=77; missing=0.
- **job** — Bank Marketing column job; list: admin.; blue-collar; entrepreneur; housemaid; management; retired; self-employed; services; student; technician; unemployed; distinct=12; missing=288.
- **marital** — Bank Marketing column marital; list: divorced; married; single; distinct=3; missing=0.
- **education** — Bank Marketing column education; list: primary; secondary; tertiary; distinct=4; missing=1857.
- **default** — Bank Marketing column default; list: no; yes; distinct=2; missing=0.
- **balance** — Bank Marketing column balance; integer: range -8019 to 102127; distinct=7168; missing=0.
- **housing** — Bank Marketing column housing; list: no; yes; distinct=2; missing=0.
- **loan** — Bank Marketing column loan; list: no; yes; distinct=2; missing=0.
- **contact** — Bank Marketing column contact; list: cellular; telephone; distinct=3; missing=13020.
- **day_of_week** — Bank Marketing column day_of_week; integer: range 1 to 31; distinct=31; missing=0.
- **month** — Bank Marketing column month; list: apr; aug; dec; feb; jan; jul; jun; mar; may; nov; oct; sep; distinct=12; missing=0.
- **duration** — Bank Marketing column duration; integer: range 0 to 4918; distinct=1573; missing=0.
- **campaign** — Bank Marketing column campaign; integer: range 1 to 63; distinct=48; missing=0.
- **pdays** — Bank Marketing column pdays; integer: range -1 to 871; distinct=559; missing=0.
- **previous** — Bank Marketing column previous; integer: range 0 to 275; distinct=41; missing=0.
- **poutcome** — Bank Marketing column poutcome; list: failure; other; success; distinct=4; missing=36959.
- **y** — Bank Marketing column y; list: no; yes; distinct=2; missing=0.

## census_income_kdd_117

199523 rows; 42 columns.

- **AAGE** — Census-Income (KDD) column AAGE; integer: range 0 to 90; distinct=91; missing=0.
- **ACLSWKR** — Census-Income (KDD) column ACLSWKR; list:  Federal government;  Local government;  Never worked;  Not in universe;  Private;  Self-employed-incorporated;  Self-employed-not incorporated;  State government;  Without pay; distinct=9; missing=0.
- **ADTINK** — Census-Income (KDD) column ADTINK; integer: range 0 to 51; distinct=52; missing=0.
- **ADTOCC** — Census-Income (KDD) column ADTOCC; integer: range 0 to 46; distinct=47; missing=0.
- **AHGA** — Census-Income (KDD) column AHGA; list:  10th grade;  11th grade;  12th grade no diploma;  1st 2nd 3rd or 4th grade;  5th or 6th grade;  7th and 8th grade;  9th grade;  Associates degree-academic program;  Associates degree-occup /vocational;  Bachelors degree(BA AB BS);  Children;  Doctorate degree(PhD EdD);  High school graduate;  Less than 1st grade;  Masters degree(MA MS MEng MEd MSW MBA);  Prof school degree (MD DDS DVM LLB JD);  Some college but no degree; distinct=17; missing=0.
- **AHSCOL** — Census-Income (KDD) column AHSCOL; list:  College or university;  High school;  Not in universe; distinct=3; missing=0.
- **AMARITL** — Census-Income (KDD) column AMARITL; list:  Divorced;  Married-A F spouse present;  Married-civilian spouse present;  Married-spouse absent;  Never married;  Separated;  Widowed; distinct=7; missing=0.
- **AMJIND** — Census-Income (KDD) column AMJIND; list:  Agriculture;  Armed Forces;  Business and repair services;  Communications;  Construction;  Education;  Entertainment;  Finance insurance and real estate;  Forestry and fisheries;  Hospital services;  Manufacturing-durable goods;  Manufacturing-nondurable goods;  Medical except hospital;  Mining;  Not in universe or children;  Other professional services;  Personal services except private HH;  Private household services;  Public administration;  Retail trade;  Social services;  Transportation;  Utilities and sanitary services;  Wholesale trade; distinct=24; missing=0.
- **AMJOCC** — Census-Income (KDD) column AMJOCC; list:  Adm support including clerical;  Armed Forces;  Executive admin and managerial;  Farming forestry and fishing;  Handlers equip cleaners etc ;  Machine operators assmblrs & inspctrs;  Not in universe;  Other service;  Precision production craft & repair;  Private household services;  Professional specialty;  Protective services;  Sales;  Technicians and related support;  Transportation and material moving; distinct=15; missing=0.
- **ARACE** — Census-Income (KDD) column ARACE; list:  Amer Indian Aleut or Eskimo;  Asian or Pacific Islander;  Black;  Other;  White; distinct=5; missing=0.
- **AREORGN** — Census-Income (KDD) column AREORGN; list:  All other;  Central or South American;  Chicano;  Cuban;  Do not know;  Mexican (Mexicano);  Mexican-American;  NA;  Other Spanish;  Puerto Rican; distinct=10; missing=0.
- **ASEX** — Census-Income (KDD) column ASEX; list:  Female;  Male; distinct=2; missing=0.
- **AUNMEM** — Census-Income (KDD) column AUNMEM; list:  No;  Not in universe;  Yes; distinct=3; missing=0.
- **AUNTYPE** — Census-Income (KDD) column AUNTYPE; list:  Job leaver;  Job loser - on layoff;  New entrant;  Not in universe;  Other job loser;  Re-entrant; distinct=6; missing=0.
- **AWKSTAT** — Census-Income (KDD) column AWKSTAT; list:  Children or Armed Forces;  Full-time schedules;  Not in labor force;  PT for econ reasons usually FT;  PT for econ reasons usually PT;  PT for non-econ reasons usually FT;  Unemployed full-time;  Unemployed part- time; distinct=8; missing=0.
- **CAPGAIN** — Census-Income (KDD) column CAPGAIN; integer: range 0 to 99999; distinct=132; missing=0.
- **GAPLOSS** — Census-Income (KDD) column GAPLOSS; integer: range 0 to 4608; distinct=113; missing=0.
- **DIVVAL** — Census-Income (KDD) column DIVVAL; integer: range 0 to 99999; distinct=1478; missing=0.
- **FILESTAT** — Census-Income (KDD) column FILESTAT; list:  Head of household;  Joint both 65+;  Joint both under 65;  Joint one under 65 & one 65+;  Nonfiler;  Single; distinct=6; missing=0.
- **GRINREG** — Census-Income (KDD) column GRINREG; list:  Abroad;  Midwest;  Northeast;  Not in universe;  South;  West; distinct=6; missing=0.
- **GRINST** — Census-Income (KDD) column GRINST; list:  Abroad;  Alabama;  Alaska;  Arizona;  Arkansas;  California;  Colorado;  Connecticut;  Delaware;  District of Columbia;  Florida;  Georgia;  Idaho;  Illinois;  Indiana;  Iowa;  Kansas;  Kentucky;  Louisiana;  Maine;  Maryland;  Massachusetts;  Michigan;  Minnesota;  Mississippi;  Missouri;  Montana;  Nebraska;  Nevada;  New Hampshire;  New Jersey;  New Mexico;  New York;  North Carolina;  North Dakota;  Not in universe;  Ohio;  Oklahoma;  Oregon;  Pennsylvania;  South Carolina;  South Dakota;  Tennessee;  Texas;  Utah;  Vermont;  Virginia;  West Virginia;  Wisconsin;  Wyoming; distinct=51; missing=708.
- **HHDFMX** — Census-Income (KDD) column HHDFMX; list:  Child 18+ ever marr Not in a subfamily;  Child 18+ ever marr RP of subfamily;  Child 18+ never marr Not in a subfamily;  Child 18+ never marr RP of subfamily;  Child 18+ spouse of subfamily RP;  Child <18 ever marr RP of subfamily;  Child <18 ever marr not in subfamily;  Child <18 never marr RP of subfamily;  Child <18 never marr not in subfamily;  Child <18 spouse of subfamily RP;  Child under 18 of RP of unrel subfamily;  Grandchild 18+ ever marr RP of subfamily;  Grandchild 18+ ever marr not in subfamily;  Grandchild 18+ never marr RP of subfamily;  Grandchild 18+ never marr not in subfamily;  Grandchild 18+ spouse of subfamily RP;  Grandchild <18 ever marr not in subfamily;  Grandchild <18 never marr RP of subfamily;  Grandchild <18 never marr child of subfamily RP;  Grandchild <18 never marr not in subfamily;  Householder;  In group quarters;  Nonfamily householder;  Other Rel 18+ ever marr RP of subfamily;  Other Rel 18+ ever marr not in subfamily;  Other Rel 18+ never marr RP of subfamily;  Other Rel 18+ never marr not in subfamily;  Other Rel 18+ spouse of subfamily RP;  Other Rel <18 ever marr RP of subfamily;  Other Rel <18 ever marr not in subfamily;  Other Rel <18 never marr child of subfamily RP;  Other Rel <18 never marr not in subfamily;  Other Rel <18 never married RP of subfamily;  Other Rel <18 spouse of subfamily RP;  RP of unrelated subfamily;  Secondary individual;  Spouse of RP of unrelated subfamily;  Spouse of householder; distinct=38; missing=0.
- **HHDREL** — Census-Income (KDD) column HHDREL; list:  Child 18 or older;  Child under 18 ever married;  Child under 18 never married;  Group Quarters- Secondary individual;  Householder;  Nonrelative of householder;  Other relative of householder;  Spouse of householder; distinct=8; missing=0.
- **MARSUPWRT** — Census-Income (KDD) column MARSUPWRT; real: range 37.87 to 18656.3; distinct=99800; missing=0.
- **MIGMTR1** — Census-Income (KDD) column MIGMTR1; list:  Abroad to MSA;  Abroad to nonMSA;  MSA to MSA;  MSA to nonMSA;  NonMSA to MSA;  NonMSA to nonMSA;  Nonmover;  Not identifiable;  Not in universe; distinct=10; missing=99696.
- **MIGMTR3** — Census-Income (KDD) column MIGMTR3; list:  Abroad;  Different county same state;  Different division same region;  Different region;  Different state same division;  Nonmover;  Not in universe;  Same county; distinct=9; missing=99696.
- **MIGMTR4** — Census-Income (KDD) column MIGMTR4; list:  Abroad;  Different county same state;  Different state in Midwest;  Different state in Northeast;  Different state in South;  Different state in West;  Nonmover;  Not in universe;  Same county; distinct=10; missing=99696.
- **MIGSAME** — Census-Income (KDD) column MIGSAME; list:  No;  Not in universe under 1 year old;  Yes; distinct=3; missing=0.
- **MIGSUN** — Census-Income (KDD) column MIGSUN; list:  No;  Not in universe;  Yes; distinct=4; missing=99696.
- **NOEMP** — Census-Income (KDD) column NOEMP; integer: range 0 to 6; distinct=7; missing=0.
- **PARENT** — Census-Income (KDD) column PARENT; list:  Both parents present;  Father only present;  Mother only present;  Neither parent present;  Not in universe; distinct=5; missing=0.
- **PEFNTVTY** — Census-Income (KDD) column PEFNTVTY; list:  Cambodia;  Canada;  China;  Columbia;  Cuba;  Dominican-Republic;  Ecuador;  El-Salvador;  England;  France;  Germany;  Greece;  Guatemala;  Haiti;  Holand-Netherlands;  Honduras;  Hong Kong;  Hungary;  India;  Iran;  Ireland;  Italy;  Jamaica;  Japan;  Laos;  Mexico;  Nicaragua;  Outlying-U S (Guam USVI etc);  Panama;  Peru;  Philippines;  Poland;  Portugal;  Puerto-Rico;  Scotland;  South Korea;  Taiwan;  Thailand;  Trinadad&Tobago;  United-States;  Vietnam;  Yugoslavia; distinct=43; missing=6713.
- **PEMNTVTY** — Census-Income (KDD) column PEMNTVTY; list:  Cambodia;  Canada;  China;  Columbia;  Cuba;  Dominican-Republic;  Ecuador;  El-Salvador;  England;  France;  Germany;  Greece;  Guatemala;  Haiti;  Holand-Netherlands;  Honduras;  Hong Kong;  Hungary;  India;  Iran;  Ireland;  Italy;  Jamaica;  Japan;  Laos;  Mexico;  Nicaragua;  Outlying-U S (Guam USVI etc);  Panama;  Peru;  Philippines;  Poland;  Portugal;  Puerto-Rico;  Scotland;  South Korea;  Taiwan;  Thailand;  Trinadad&Tobago;  United-States;  Vietnam;  Yugoslavia; distinct=43; missing=6119.
- **PENATVTY** — Census-Income (KDD) column PENATVTY; list:  Cambodia;  Canada;  China;  Columbia;  Cuba;  Dominican-Republic;  Ecuador;  El-Salvador;  England;  France;  Germany;  Greece;  Guatemala;  Haiti;  Holand-Netherlands;  Honduras;  Hong Kong;  Hungary;  India;  Iran;  Ireland;  Italy;  Jamaica;  Japan;  Laos;  Mexico;  Nicaragua;  Outlying-U S (Guam USVI etc);  Panama;  Peru;  Philippines;  Poland;  Portugal;  Puerto-Rico;  Scotland;  South Korea;  Taiwan;  Thailand;  Trinadad&Tobago;  United-States;  Vietnam;  Yugoslavia; distinct=43; missing=3393.
- **PRCITSHP** — Census-Income (KDD) column PRCITSHP; list:  Foreign born- Not a citizen of U S ;  Foreign born- U S citizen by naturalization;  Native- Born abroad of American Parent(s);  Native- Born in Puerto Rico or U S Outlying;  Native- Born in the United States; distinct=5; missing=0.
- **SEOTR** — Census-Income (KDD) column SEOTR; integer: range 0 to 2; distinct=3; missing=0.
- **VETQVA** — Census-Income (KDD) column VETQVA; list:  No;  Not in universe;  Yes; distinct=3; missing=0.
- **VETYN** — Census-Income (KDD) column VETYN; integer: range 0 to 2; distinct=3; missing=0.
- **WKSWORK** — Census-Income (KDD) column WKSWORK; integer: range 0 to 52; distinct=53; missing=0.
- **AHRSPAY** — Census-Income (KDD) column AHRSPAY; integer: range 0 to 9999; distinct=1240; missing=0.
- **year** — Census-Income (KDD) column year; integer: range 94 to 95; distinct=2; missing=0.
- **income** — Census-Income (KDD) column income; list:  50000+.; -50000; distinct=2; missing=0.

## support2_880

9105 rows; 45 columns.

- **age** — SUPPORT2 column age; real: range 18.04199 to 101.84796; distinct=7323; missing=0.
- **sex** — SUPPORT2 column sex; list: female; male; distinct=2; missing=0.
- **dzgroup** — SUPPORT2 column dzgroup; list: ARF/MOSF w/Sepsis; CHF; COPD; Cirrhosis; Colon Cancer; Coma; Lung Cancer; MOSF w/Malig; distinct=8; missing=0.
- **dzclass** — SUPPORT2 column dzclass; list: ARF/MOSF; COPD/CHF/Cirrhosis; Cancer; Coma; distinct=4; missing=0.
- **num.co** — SUPPORT2 column num.co; integer: range 0 to 9; distinct=10; missing=0.
- **edu** — SUPPORT2 column edu; real: range 0.0 to 31.0; distinct=32; missing=1634.
- **income** — SUPPORT2 column income; list: $11-$25k; $25-$50k; >$50k; under $11k; distinct=5; missing=2982.
- **scoma** — SUPPORT2 column scoma; real: range 0.0 to 100.0; distinct=12; missing=1.
- **charges** — SUPPORT2 column charges; real: range 1169.0 to 1435423.0; distinct=8502; missing=172.
- **totcst** — SUPPORT2 column totcst; real: range 0.0 to 633212.0; distinct=8198; missing=888.
- **totmcst** — SUPPORT2 column totmcst; real: range -102.71997 to 710682.0; distinct=5517; missing=3475.
- **avtisst** — SUPPORT2 column avtisst; real: range 1.0 to 83.0; distinct=353; missing=82.
- **race** — SUPPORT2 column race; list: asian; black; hispanic; other; white; distinct=6; missing=42.
- **sps** — SUPPORT2 column sps; real: range 0.1999817 to 99.1875; distinct=605; missing=1.
- **aps** — SUPPORT2 column aps; real: range 0.0 to 143.0; distinct=126; missing=1.
- **surv2m** — SUPPORT2 column surv2m; real: range 0.0 to 0.969970703; distinct=950; missing=1.
- **surv6m** — SUPPORT2 column surv6m; real: range 0.0 to 0.947998047; distinct=937; missing=1.
- **hday** — SUPPORT2 column hday; integer: range 1 to 148; distinct=85; missing=0.
- **diabetes** — SUPPORT2 column diabetes; integer: range 0 to 1; distinct=2; missing=0.
- **dementia** — SUPPORT2 column dementia; integer: range 0 to 1; distinct=2; missing=0.
- **ca** — SUPPORT2 column ca; list: metastatic; no; yes; distinct=3; missing=0.
- **prg2m** — SUPPORT2 column prg2m; real: range 0.0 to 1.0; distinct=52; missing=1649.
- **prg6m** — SUPPORT2 column prg6m; real: range 0.0 to 1.0; distinct=88; missing=1633.
- **dnr** — SUPPORT2 column dnr; list: dnr after sadm; dnr before sadm; no dnr; distinct=4; missing=30.
- **dnrday** — SUPPORT2 column dnrday; real: range -88.0 to 285.0; distinct=178; missing=30.
- **meanbp** — SUPPORT2 column meanbp; real: range 0.0 to 195.0; distinct=165; missing=1.
- **wblc** — SUPPORT2 column wblc; real: range 0.0 to 200.0; distinct=500; missing=212.
- **hrt** — SUPPORT2 column hrt; real: range 0.0 to 300.0; distinct=187; missing=1.
- **resp** — SUPPORT2 column resp; real: range 0.0 to 90.0; distinct=67; missing=1.
- **temp** — SUPPORT2 column temp; real: range 31.69922 to 41.69531; distinct=99; missing=1.
- **pafi** — SUPPORT2 column pafi; real: range 12.0 to 890.375; distinct=1458; missing=2325.
- **alb** — SUPPORT2 column alb; real: range 0.3999634 to 29.0; distinct=61; missing=3372.
- **bili** — SUPPORT2 column bili; real: range 0.09999084 to 63.0; distinct=296; missing=2601.
- **crea** — SUPPORT2 column crea; real: range 0.09999084 to 21.5; distinct=131; missing=67.
- **sod** — SUPPORT2 column sod; real: range 110.0 to 181.0; distinct=61; missing=1.
- **ph** — SUPPORT2 column ph; real: range 6.829102 to 7.769531; distinct=78; missing=2284.
- **glucose** — SUPPORT2 column glucose; real: range 0.0 to 1092.0; distinct=440; missing=4500.
- **bun** — SUPPORT2 column bun; real: range 1.0 to 300.0; distinct=160; missing=4352.
- **urine** — SUPPORT2 column urine; real: range 0.0 to 9000.0; distinct=1495; missing=4862.
- **adlp** — SUPPORT2 column adlp; real: range 0.0 to 7.0; distinct=9; missing=5641.
- **adls** — SUPPORT2 column adls; real: range 0.0 to 7.0; distinct=9; missing=2867.
- **adlsc** — SUPPORT2 column adlsc; real: range 0.0 to 7.0732422; distinct=1735; missing=0.
- **death** — SUPPORT2 column death; integer: range 0 to 1; distinct=2; missing=0.
- **hospdead** — SUPPORT2 column hospdead; integer: range 0 to 1; distinct=2; missing=0.
- **sfdm2** — SUPPORT2 column sfdm2; list: <2 mo. follow-up; Coma or Intub; SIP>=30; adl>=4 (>=5 if sur); no(M2 and SIP pres); distinct=6; missing=1400.
