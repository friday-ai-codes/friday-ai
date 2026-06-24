/**
 * 「Star 迸发」Lottie 动画（手工编写的 Bodymovin JSON）。
 *
 * 用于「给个 Star」入口：静止时停在第 0 帧——一颗完整的金色五角星；
 * 鼠标移入时从头播放一次的「点赞迸发」效果：
 *   1. 主星先轻微压扁再带弹性回弹（squash & stretch + back overshoot），
 *      叠加一点俏皮摆动，首尾帧都回到 scale 100，播完自然静止；
 *   2. 四周一圈放射状金光向外迸射后收敛消失；
 *   3. 一道金色光环从星心扩散淡出，增强层次。
 *
 * 与 pulseRings / deepOrbit 一样用 TS 模块导出规避 resolveJsonModule，
 * 并复用同款 LINEAR 缓动以保证 lottie-web 解析稳定。星形直接用 polystar
 * （`ty: 'sr'`, `sy: 1`）绘制，避免手写贝塞尔路径。
 */

/** 线性缓动（贝塞尔控制点落在对角线上），与 pulseRings 保持一致 */
const LINEAR = {
  o: { x: [0.167], y: [0.167] },
  i: { x: [0.833], y: [0.833] },
}

/** Friday 金色 #FBBF24 → rgb 归一化（主星填充） */
const GOLD = [0.984, 0.749, 0.141, 1]
/** 深金描边，给星星轮廓立体感 */
const GOLD_DEEP = [0.85, 0.47, 0.02, 1]
/** 放射光线 / 光环用的亮金 */
const GOLD_LIGHT = [1, 0.82, 0.32, 1]

/** 关键帧构造：dims=1 标量（旋转/透明度），dims=3 缩放 [v, v, 100] */
function toKeyframes(points: Array<[number, number]>, dims: 1 | 3) {
  const frames = points.map(([t, v]) => ({
    t,
    s: dims === 1 ? [v] : [v, v, 100],
    ...LINEAR,
  }))
  const last = frames[frames.length - 1] as Record<string, any>
  delete last.o
  delete last.i
  return { a: 1, k: frames }
}

/** 标准 transform（lottie 对 sk/sa 缺失敏感，必须补全）；每次返回新对象 */
function tr(p: [number, number] = [0, 0]) {
  return {
    ty: 'tr',
    p: { a: 0, k: p },
    a: { a: 0, k: [0, 0] },
    s: { a: 0, k: [100, 100] },
    r: { a: 0, k: 0 },
    o: { a: 0, k: 100 },
    sk: { a: 0, k: 0 },
    sa: { a: 0, k: 0 },
    nm: 'tr',
  }
}

/** 主星图层：首尾 scale 100，中段压扁→弹起→回稳，叠加轻摆 */
function starLayer() {
  return {
    ddd: 0,
    ind: 1,
    ty: 4,
    nm: 'star',
    sr: 1,
    ao: 0,
    bm: 0,
    ks: {
      o: { a: 0, k: 100 },
      r: toKeyframes([[0, 0], [7, -16], [20, 6], [31, 0]], 1),
      p: { a: 0, k: [60, 60, 0] },
      a: { a: 0, k: [0, 0, 0] },
      s: toKeyframes([[0, 100], [5, 80], [14, 116], [23, 95], [31, 100]], 3),
    },
    shapes: [
      {
        ty: 'gr',
        nm: 'star-g',
        np: 3,
        bm: 0,
        hd: false,
        it: [
          {
            ty: 'sr',
            nm: 'star-shape',
            sy: 1,
            d: 1,
            pt: { a: 0, k: 5 },
            p: { a: 0, k: [0, 0] },
            r: { a: 0, k: 0 },
            ir: { a: 0, k: 14 },
            is: { a: 0, k: 0 },
            or: { a: 0, k: 32 },
            os: { a: 0, k: 0 },
          },
          { ty: 'fl', nm: 'fill', c: { a: 0, k: GOLD }, o: { a: 0, k: 100 }, r: 1, bm: 0 },
          { ty: 'st', nm: 'stroke', c: { a: 0, k: GOLD_DEEP }, o: { a: 0, k: 100 }, w: { a: 0, k: 2 }, lc: 2, lj: 2, bm: 0 },
          tr(),
        ],
      },
    ],
    ip: 0,
    op: 44,
    st: 0,
  }
}

/** 扩散光环图层：从星心向外扩散并淡出 */
function ringLayer() {
  return {
    ddd: 0,
    ind: 2,
    ty: 4,
    nm: 'ring',
    sr: 1,
    ao: 0,
    bm: 0,
    ks: {
      o: toKeyframes([[2, 0], [7, 65], [24, 0]], 1),
      r: { a: 0, k: 0 },
      p: { a: 0, k: [60, 60, 0] },
      a: { a: 0, k: [0, 0, 0] },
      s: toKeyframes([[2, 45], [24, 140]], 3),
    },
    shapes: [
      {
        ty: 'gr',
        nm: 'ring-g',
        np: 2,
        bm: 0,
        hd: false,
        it: [
          { ty: 'el', nm: 'ring', d: 1, p: { a: 0, k: [0, 0] }, s: { a: 0, k: [62, 62] } },
          { ty: 'st', nm: 'stroke', c: { a: 0, k: GOLD_LIGHT }, o: { a: 0, k: 100 }, w: { a: 0, k: 3 }, lc: 2, lj: 2, bm: 0 },
          tr(),
        ],
      },
    ],
    ip: 0,
    op: 44,
    st: 0,
  }
}

/**
 * 放射光线图层：一条圆头短线置于星心正上方，layer 旋转到对应角度，
 *  整层 scale 从 0 迸出再收敛，配合透明度闪现，形成放射爆开。
 */
function rayLayer(ind: number, angle: number, t0: number) {
  return {
    ddd: 0,
    ind,
    ty: 4,
    nm: `ray-${ind}`,
    sr: 1,
    ao: 0,
    bm: 0,
    ks: {
      o: toKeyframes([[t0, 0], [t0 + 4, 100], [t0 + 15, 0]], 1),
      r: { a: 0, k: angle },
      p: { a: 0, k: [60, 60, 0] },
      a: { a: 0, k: [0, 0, 0] },
      s: toKeyframes([[t0, 10], [t0 + 7, 118], [t0 + 15, 72]], 3),
    },
    shapes: [
      {
        ty: 'gr',
        nm: 'ray-g',
        np: 2,
        bm: 0,
        hd: false,
        it: [
          { ty: 'rc', nm: 'ray', d: 1, p: { a: 0, k: [0, -40] }, s: { a: 0, k: [3.4, 14] }, r: { a: 0, k: 1.7 } },
          { ty: 'fl', nm: 'fill', c: { a: 0, k: GOLD_LIGHT }, o: { a: 0, k: 100 }, r: 1, bm: 0 },
          tr(),
        ],
      },
    ],
    ip: 0,
    op: 44,
    st: 0,
  }
}

/** 8 条放射光线，每隔 45° 一条，整齐爆开（同帧迸出） */
const RAYS = Array.from({ length: 8 }, (_, i) => rayLayer(i + 3, i * 45, 2))

const starBurstAnimation: Record<string, any> = {
  v: '5.9.0',
  fr: 60,
  ip: 0,
  op: 44,
  w: 120,
  h: 120,
  nm: 'friday-star-burst',
  ddd: 0,
  assets: [],
  // 数组靠前者渲染在上层：主星置顶，光环与放射线在其后
  layers: [starLayer(), ringLayer(), ...RAYS],
}

export default starBurstAnimation
