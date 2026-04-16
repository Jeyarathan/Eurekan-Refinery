// Preset groups
export const CHAIN_PRESETS = [
  {
    id: 'p_gas', name: 'Gasoline Chain',
    units: ['cdu_1', 'splitter_1', 'nht_1', 'reformer_1', 'fcc_1', 'scanfiner_1', 'alky_1'],
    color: '#3b82f6',
    product: 'Gasoline 43K bbl/d — $3.55M/d',
    flow: [
      { f: 'Crude Feed', t: 'CDU 1', s: '80K bbl/d', v: 80 },
      { f: 'CDU 1', t: 'Nap Splitter', s: 'Naphtha 42K', v: 42 },
      { f: 'Nap Splitter', t: 'LN → Blender', s: 'LN 24K', v: 24 },
      { f: 'Nap Splitter', t: 'Naphtha HT', s: 'HN 18K', v: 18 },
      { f: 'Naphtha HT', t: 'Reformer', s: 'Treated HN 18K', v: 18 },
      { f: 'Reformer', t: 'Blend', s: 'Reformate 10K (RON 100+)', v: 10 },
      { f: 'CDU 1', t: 'FCC 1', s: 'VGO 38K', v: 38 },
      { f: 'FCC 1', t: 'Blend', s: 'LCN 5K (RON 93)', v: 5 },
      { f: 'FCC 1', t: 'Alkylation', s: 'C3/C4 2K', v: 2 },
      { f: 'Alkylation', t: 'Blend', s: 'Alkylate 2K (RON 96)', v: 2 },
    ],
    specs: [
      { sp: 'RON', val: '87.0', lim: '\u2265 87.0', mar: '0.0', st: 'binding' },
      { sp: 'Sulfur', val: '28 ppm', lim: '\u2264 30 ppm', mar: '2 ppm', st: 'tight' },
      { sp: 'RVP', val: '7.4 psi', lim: '\u2264 9.0', mar: '1.6 psi', st: 'ok' },
      { sp: 'Benzene', val: '0.42%', lim: '\u2264 0.62%', mar: '0.20%', st: 'ok' },
    ],
    blend: [
      { c: 'Light Naphtha', vol: '24K', pct: '55.8%', ron: '72.0', s: '<1' },
      { c: 'Reformate', vol: '10K', pct: '23.3%', ron: '100.2', s: '<1' },
      { c: 'LCN (FCC)', vol: '5K', pct: '11.6%', ron: '93.2', s: '32' },
      { c: 'HCN (FCC)', vol: '2K', pct: '4.7%', ron: '80.1', s: '820' },
      { c: 'Alkylate', vol: '2K', pct: '4.7%', ron: '96.0', s: '0' },
    ],
  },
  {
    id: 'p_dist', name: 'Distillate Chain',
    units: ['cdu_1', 'kht_1', 'dht_1'],
    color: '#06b6d4',
    product: 'Jet 17K + Diesel 11K — $2.22M/d',
    flow: [
      { f: 'CDU 1', t: 'Kero HT', s: 'Kero 17K', v: 17 },
      { f: 'Kero HT', t: 'Jet', s: 'Jet 17K', v: 17 },
      { f: 'CDU 1', t: 'Diesel HT', s: 'Diesel 1K', v: 1 },
      { f: 'FCC LCO', t: 'Diesel HT', s: 'LCO 10K', v: 10 },
      { f: 'Diesel HT', t: 'ULSD', s: 'Diesel 11K', v: 11 },
    ],
    specs: [
      { sp: 'Jet Smoke', val: '22mm', lim: '\u2265 18', mar: '4mm', st: 'ok' },
      { sp: 'Diesel S', val: '12ppm', lim: '\u2264 15', mar: '3ppm', st: 'tight' },
      { sp: 'Cetane', val: '46.2', lim: '\u2265 40', mar: '6.2', st: 'ok' },
    ],
    blend: [],
  },
  {
    id: 'p_hvy', name: 'Heavy End',
    units: ['cdu_1', 'vacuum_1', 'coker_1'],
    color: '#f59e0b',
    product: 'Fuel Oil 10K — $520K/d',
    flow: [
      { f: 'CDU 1', t: 'Resid', s: 'Resid 10K', v: 10 },
      { f: 'Resid', t: 'Fuel Oil', s: 'Direct 10K', v: 10 },
    ],
    specs: [],
    blend: [],
  },
  {
    id: 'p_lpg', name: 'LPG / Light Ends',
    units: ['fcc_1', 'alky_1'],
    color: '#ec4899',
    product: 'LPG 1K — $64K/d',
    flow: [
      { f: 'FCC 1', t: 'Gas Plant', s: 'C3/C4', v: 3 },
      { f: 'Gas Plant', t: 'Alkylation', s: '2K', v: 2 },
      { f: 'Gas Plant', t: 'LPG', s: '1K', v: 1 },
    ],
    specs: [],
    blend: [],
  },
]

export const DOMAIN_PRESETS = [
  {
    id: 'd_crude', name: 'Crude & CDU',
    units: ['cdu_1'], color: '#3b82f6',
    desc: 'Crude selection and CDU operation',
    decisions: [
      { d: 'Crude slate', c: 'KWT 14K, MRY 30K, MYA 12K, NGM 24K', i: 'NGM/MRY zero reduced cost \u2014 degenerate' },
      { d: 'CDU throughput', c: '80K (100% \u2014 binding)', i: 'Shadow $4.82/bbl \u2014 top debottleneck' },
    ],
    headers: ['Crude', 'Rate', 'Price', 'Cost/d', 'Red.Cost'],
    data: [
      ['KWT', '14K', '$70.2', '$983K', '$2.40'],
      ['MRY', '30K', '$64.8', '$1,944K', '\u22480'],
      ['MYA', '12K', '$58.1', '$697K', '$1.80'],
      ['NGM', '24K', '$72.4', '$1,738K', '\u22480'],
    ],
  },
  {
    id: 'd_conv', name: 'Conversion & Cracking',
    units: ['goht_1', 'fcc_1', 'vacuum_1', 'coker_1'], color: '#8b5cf6',
    desc: 'FCC severity, feed, cracking economics',
    decisions: [
      { d: 'FCC conversion', c: '68.0% (below peak ~72%)', i: 'Regen temp limits \u2014 $2.15/\u00b0F shadow' },
      { d: 'Vacuum/Coker', c: 'Inactive', i: 'Would convert $52 FO \u2192 $70+ products' },
    ],
    headers: ['Param', 'Value', 'Detail'],
    data: [
      ['FCC Conv', '68.0%', 'Gasoline 48.2vol%'],
      ['Regen', '1,209\u00b0F', '93% of 1,300\u00b0F limit'],
      ['Coke', '5.8wt%', '32 T/min circ'],
    ],
  },
  {
    id: 'd_treat', name: 'Treating & Blending',
    units: ['nht_1', 'reformer_1', 'scanfiner_1', 'kht_1', 'dht_1'], color: '#06b6d4',
    desc: 'Hydrotreaters, Scanfiner, product specs',
    decisions: [
      { d: 'Reformer', c: '29% util, RON 100.2', i: 'Room to push \u2014 more reformate relaxes RON' },
      { d: 'Scanfiner', c: 'Inactive', i: 'Activating removes biggest S contributor' },
    ],
    headers: ['Spec', 'Value', 'Limit', 'Util', 'Shadow'],
    data: [
      ['Gas RON', '87.0', '\u2265 87.0', 'BINDING', '$1.12'],
      ['Gas S', '28ppm', '\u2264 30', '93%', '$1.87'],
      ['Gas RVP', '7.4', '\u2264 9.0', '82%', '$0.18'],
    ],
  },
  {
    id: 'd_le', name: 'Light Ends',
    units: ['alky_1', 'isom_c4', 'isom_c56'], color: '#f59e0b',
    desc: 'Alkylation, isomerization',
    decisions: [
      { d: 'Alky feed', c: '2K from FCC C3/C4', i: 'Cap 14K \u2014 heavily underutilized' },
      { d: 'Isom (future)', c: 'Not built', i: 'LN RON 72\u219282 \u2014 relaxes binding RON' },
    ],
    headers: ['Unit', 'Rate', 'Cap', 'Util', 'Output'],
    data: [['Alkylation', '2K', '14K cap', '14%', 'RON 96']],
  },
]

export const IMPACTS = [
  { id: 1, action: 'Increase CDU capacity +2K bbl/d', delta: '+$28K/d', from: '80,000', to: '82,000', cat: 'debottleneck', conf: 'high' },
  { id: 2, action: 'Relax gasoline sulfur to 35 ppm', delta: '+$15K/d', from: '30 ppm', to: '35 ppm', cat: 'spec', conf: 'high' },
  { id: 3, action: 'Push Reformer to 85% utilization', delta: '+$11K/d', from: '72%', to: '85%', cat: 'debottleneck', conf: 'high' },
  { id: 4, action: 'Swap 5K KWT \u2192 MRY (degenerate)', delta: '+$8K/d', from: 'KWT: 14K', to: 'KWT: 9K, MRY: 35K', cat: 'crude', conf: 'medium' },
  { id: 5, action: 'Increase FCC regen limit +15\u00b0F', delta: '+$6K/d', from: '1,300\u00b0F', to: '1,315\u00b0F', cat: 'equipment', conf: 'medium' },
]

export const TRACES: Record<string, {
  label: string
  spec: string
  margin: string
  bind: boolean
  steps: Array<{ d: number; l: string; v: string; t: string; desc: string }>
}> = {
  sulfur: {
    label: 'Gasoline Sulfur = 28 ppm', spec: '\u2264 30 ppm', margin: '2 ppm (6.7%)', bind: false,
    steps: [
      { d: 0, l: 'Gasoline Sulfur', v: '28 ppm', t: 'out', desc: 'Volume-weighted sulfur of all blend components' },
      { d: 1, l: 'HCN Sulfur \u00d7 23.5%', v: '= 193', t: 'dom', desc: 'FCC heavy cat naphtha \u2014 DOMINANT contributor' },
      { d: 2, l: 'HCN Sulfur', v: '820 ppm', t: 'eq', desc: 'S_hcn = \u03b5\u2081\u00b7S_feed\u00b7(1-Conv/100)^\u03b5\u2082' },
      { d: 3, l: 'FCC Feed Sulfur', v: '1.2 wt%', t: 'in', desc: 'From VGO blend \u2014 crude dependent' },
      { d: 3, l: 'FCC Conversion', v: '68.0%', t: 'in', desc: 'Higher Conv \u2192 less HCN sulfur' },
      { d: 1, l: 'LCN Sulfur \u00d7 11.6%', v: '= 3.7', t: 'c', desc: 'FCC light cat naphtha' },
      { d: 1, l: 'Reformate \u00d7 23.3%', v: '< 0.1', t: 'c', desc: 'Near zero sulfur' },
      { d: 1, l: 'Alkylate \u00d7 4.7%', v: '= 0', t: 'c', desc: 'Zero sulfur' },
    ],
  },
  ron: {
    label: 'Gasoline RON = 87.0', spec: '\u2265 87.0', margin: '0.0 \u2014 BINDING', bind: true,
    steps: [
      { d: 0, l: 'Gasoline RON', v: '87.0', t: 'out', desc: 'Volumetric blending of all components' },
      { d: 1, l: 'Reformate RON \u00d7 23.3%', v: '100.2', t: 'c', desc: 'Highest octane \u2014 pulls UP' },
      { d: 1, l: 'Alkylate RON \u00d7 4.7%', v: '96.0', t: 'c', desc: 'Premium, zero sulfur too' },
      { d: 1, l: 'LCN RON \u00d7 11.6%', v: '93.2', t: 'c', desc: 'FCC light naphtha \u2014 good' },
      { d: 1, l: 'HCN RON \u00d7 4.7%', v: '80.1', t: 'dom', desc: 'Pulls blend DOWN' },
      { d: 1, l: 'LN RON \u00d7 55.8%', v: '72.0', t: 'dom', desc: 'BIGGEST octane drag' },
      { d: 2, l: 'RON is BINDING at 87.0', v: '', t: 'ins', desc: 'Shadow $1.12/unit. More reformate or alkylate improves margin. Isomerization (Stage 3) converts LN 72\u219282.' },
    ],
  },
}

export const FCC_EQS = [
  { n: 'Gasoline Yield', eq: 'Y = (\u03b1\u2081\u00b7Conv + \u03b1\u2082\u00b7Conv\u00b2 + \u03b1\u2083\u00b7API + \u03b1\u2084\u00b7CCR) \u00d7 cal', v: '48.2 vol%', vars: 'Conv=68% API=24.3 CCR=0.82 cal=1.02' },
  { n: 'Coke Yield', eq: 'Y = \u03b2\u2081\u00b7Conv + \u03b2\u2082\u00b7CCR + \u03b2\u2083\u00b7Ni + \u03b2\u2084\u00b7V', v: '5.8 wt%', vars: 'Conv=68% CCR=0.82 Ni=1.2 V=2.1' },
  { n: 'Regen Temp', eq: 'T = T\u2080 + \u03b3\u2081\u00b7Y_coke/circ + \u03b3\u2082\u00b7air', v: '1,209\u00b0F', vars: 'Y_coke=5.8% circ=32 air=185' },
  { n: 'LCN RON', eq: 'RON = \u03b4\u2081 + \u03b4\u2082\u00b7Conv + \u03b4\u2083\u00b7API', v: '93.2', vars: 'Conv=68% API=24.3' },
  { n: 'HCN Sulfur', eq: 'S = \u03b5\u2081\u00b7S_feed\u00b7(1-Conv/100)^\u03b5\u2082', v: '820 ppm', vars: 'S_feed=1.2% Conv=68%' },
]

export const BINDS = [
  { name: 'CDU Capacity', unit: 'cdu_1', util: 100, shadow: 4.82, desc: 'At max 80K bbl/d' },
  { name: 'FCC Regen Temp', unit: 'fcc_1', util: 93, shadow: 2.15, desc: '1,209\u00b0F vs 1,300\u00b0F limit' },
  { name: 'Gasoline Sulfur', unit: 'blend', util: 93, shadow: 1.87, desc: '28/30 ppm' },
  { name: 'Gasoline RON', unit: 'blend', util: 100, shadow: 1.12, desc: '87.0 \u2014 binding' },
]
