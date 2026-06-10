/**
 * 「涟漪光环」Lottie 动画（手工编写的 Bodymovin JSON）。
 *
 * 三圈 Friday 青绿描边圆环错拍向外扩散、透明度渐隐，用于 Logo / 图标
 * 背后的氛围光环。与 deepOrbit 一样用 TS 模块规避 resolveJsonModule。
 *
 * 错拍循环的实现：三个环共享同一条 180 帧的「扩散曲线」，相位各偏移
 * 60 帧。相位 > 0 的环会在时间轴中段跨过曲线的回卷点（scale 110 → 30
 * 的瞬间跳变），跳变安排在透明度为 0 的时刻 + 0.5 帧内完成，肉眼不可见。
 *
 * 注意：lottie-web 的 shape 解析对字段完整性很敏感——椭圆缺 `d`、
 * transform 缺 `sk`/`sa` 都会导致整条 path 静默渲染为空。
 */

/** 线性缓动（贝塞尔控制点落在对角线上） */
const LINEAR = {
  o: { x: [0.167], y: [0.167] },
  i: { x: [0.833], y: [0.833] },
}

interface RingKeyframes {
  /** layer scale 关键帧：[帧, 百分比] */
  scale: Array<[number, number]>
  /** layer opacity 关键帧：[帧, 0-100] */
  opacity: Array<[number, number]>
}

/** 相位 0 / 60 / 120 帧的扩散曲线（scale 30→110，opacity 0→55→0） */
const RING_PHASES: RingKeyframes[] = [
  {
    scale: [[0, 30], [180, 110]],
    opacity: [[0, 0], [20, 55], [180, 0]],
  },
  {
    scale: [[0, 56.7], [120, 110], [120.5, 30], [180, 56.7]],
    opacity: [[0, 41.3], [120, 0], [140, 55], [180, 41.3]],
  },
  {
    scale: [[0, 83.3], [60, 110], [60.5, 30], [180, 83.3]],
    opacity: [[0, 20.6], [60, 0], [80, 55], [180, 20.6]],
  },
]

function toKeyframes(points: Array<[number, number]>, dims: number) {
  const frames = points.map(([t, v]) => ({ t, s: dims === 1 ? [v] : [v, v, 100], ...LINEAR }))
  const last = frames[frames.length - 1] as Record<string, any>
  delete last.o
  delete last.i
  return { a: 1, k: frames }
}

function pulseRing(ind: number, kf: RingKeyframes) {
  return {
    ddd: 0,
    ind,
    ty: 4,
    nm: `pulse-ring-${ind}`,
    sr: 1,
    ao: 0,
    bm: 0,
    ks: {
      o: toKeyframes(kf.opacity, 1),
      r: { a: 0, k: 0 },
      p: { a: 0, k: [60, 60, 0] },
      a: { a: 0, k: [0, 0, 0] },
      s: toKeyframes(kf.scale, 3),
    },
    shapes: [
      {
        ty: 'gr',
        nm: `ring-g-${ind}`,
        np: 2,
        bm: 0,
        hd: false,
        it: [
          { ty: 'el', nm: 'ring', d: 1, p: { a: 0, k: [0, 0] }, s: { a: 0, k: [100, 100] } },
          {
            ty: 'st',
            nm: 'stroke',
            // Friday 青绿 hsl(168 76% 42%)
            c: { a: 0, k: [0.101, 0.739, 0.612, 1] },
            o: { a: 0, k: 100 },
            w: { a: 0, k: 3 },
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
  }
}

const pulseRingsAnimation: Record<string, any> = {
  v: '5.9.0',
  fr: 60,
  ip: 0,
  op: 180,
  w: 120,
  h: 120,
  nm: 'friday-pulse-rings',
  ddd: 0,
  assets: [],
  layers: RING_PHASES.map((kf, i) => pulseRing(i + 1, kf)),
}

export default pulseRingsAnimation
