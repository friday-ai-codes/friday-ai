/**
 * 「双星环绕」Lottie 动画（手工编写的 Bodymovin JSON）。
 *
 * 隐喻 Friday × Claude Code 协作：一颗 Friday 青绿星与一颗 Claude 珊瑚星
 * 沿同一条淡灰轨道对向环绕，环绕同时带轻微的呼吸缩放。
 * 用 TS 模块而非 .json 文件，规避 resolveJsonModule / 类型声明问题。
 *
 * 注意：lottie-web 的 shape 解析对字段完整性很敏感——椭圆缺 `d`、填充缺
 * `r`、transform 缺 `sk`/`sa` 都会导致整条 path 静默渲染为空。
 */

/** 线性缓动（贝塞尔控制点落在对角线上） */
const LINEAR = {
  o: { x: [0.167], y: [0.167] },
  i: { x: [0.833], y: [0.833] },
}

/** shape group 末尾的标准 transform，可叠加呼吸缩放 keyframes */
function groupTransform(scaleK: any) {
  return {
    ty: 'tr',
    p: { a: 0, k: [13, 0] },
    a: { a: 0, k: [13, 0] },
    s: scaleK,
    r: { a: 0, k: 0 },
    o: { a: 0, k: 100 },
    sk: { a: 0, k: 0 },
    sa: { a: 0, k: 0 },
    nm: 'tr',
  }
}

/** 单颗环绕星：layer 旋转产生公转，shape group 缩放产生呼吸 */
function orbitDot(opts: {
  ind: number
  name: string
  color: [number, number, number]
  /** 公转起始相位（角度） */
  phase: number
  /** 呼吸缩放错拍：false = 从小到大起拍，true = 从大到小起拍 */
  pulseInverted: boolean
}) {
  const { ind, name, color, phase, pulseInverted } = opts
  const cycle = pulseInverted ? [132, 100, 132, 100, 132] : [100, 132, 100, 132, 100]
  const scaleK = {
    a: 1,
    k: [
      ...[0, 45, 90, 135].map((t, i) => ({ t, s: [cycle[i], cycle[i]], ...LINEAR })),
      { t: 180, s: [cycle[4], cycle[4]] },
    ],
  }
  return {
    ddd: 0,
    ind,
    ty: 4,
    nm: name,
    sr: 1,
    ao: 0,
    bm: 0,
    ks: {
      o: { a: 0, k: 100 },
      r: {
        a: 1,
        k: [
          { t: 0, s: [phase], ...LINEAR },
          { t: 180, s: [phase + 360] },
        ],
      },
      p: { a: 0, k: [24, 24, 0] },
      a: { a: 0, k: [0, 0, 0] },
      s: { a: 0, k: [100, 100, 100] },
    },
    shapes: [
      {
        ty: 'gr',
        nm: `${name}-g`,
        np: 2,
        bm: 0,
        hd: false,
        it: [
          { ty: 'el', nm: 'dot', d: 1, p: { a: 0, k: [13, 0] }, s: { a: 0, k: [9, 9] } },
          { ty: 'fl', nm: 'fill', r: 1, bm: 0, c: { a: 0, k: [...color, 1] }, o: { a: 0, k: 100 } },
          groupTransform(scaleK),
        ],
      },
    ],
    ip: 0,
    op: 181,
    st: 0,
  }
}

const deepOrbitAnimation: Record<string, any> = {
  v: '5.9.0',
  fr: 60,
  ip: 0,
  op: 180,
  w: 48,
  h: 48,
  nm: 'friday-claude-orbit',
  ddd: 0,
  assets: [],
  layers: [
    // Friday 青绿星（hsl(168 76% 42%)）
    orbitDot({ ind: 1, name: 'dot-friday', color: [0.101, 0.739, 0.612], phase: 0, pulseInverted: false }),
    // Claude 珊瑚星（#D97757），对向相位
    orbitDot({ ind: 2, name: 'dot-claude', color: [0.851, 0.467, 0.341], phase: 180, pulseInverted: true }),
    // 淡灰轨道环
    {
      ddd: 0,
      ind: 3,
      ty: 4,
      nm: 'orbit-ring',
      sr: 1,
      ao: 0,
      bm: 0,
      ks: {
        o: { a: 0, k: 32 },
        r: { a: 0, k: 0 },
        p: { a: 0, k: [24, 24, 0] },
        a: { a: 0, k: [0, 0, 0] },
        s: { a: 0, k: [100, 100, 100] },
      },
      shapes: [
        {
          ty: 'gr',
          nm: 'ring-g',
          np: 2,
          bm: 0,
          hd: false,
          it: [
            { ty: 'el', nm: 'ring', d: 1, p: { a: 0, k: [0, 0] }, s: { a: 0, k: [26, 26] } },
            {
              ty: 'st',
              nm: 'stroke',
              c: { a: 0, k: [0.72, 0.77, 0.84, 1] },
              o: { a: 0, k: 100 },
              w: { a: 0, k: 2 },
              lc: 2,
              lj: 2,
              bm: 0,
            },
            {
              ty: 'tr',
              p: { a: 0, k: [0, 0] },
              a: { a: 0, k: [0, 0] },
              s: { a: 0, k: [100, 100] },
              r: { a: 0, k: 0 },
              o: { a: 0, k: 100 },
              sk: { a: 0, k: 0 },
              sa: { a: 0, k: 0 },
              nm: 'tr',
            },
          ],
        },
      ],
      ip: 0,
      op: 181,
      st: 0,
    },
  ],
}

export default deepOrbitAnimation
