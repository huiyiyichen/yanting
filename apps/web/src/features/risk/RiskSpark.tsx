const LEVELS = ['calm', 'dissatisfied', 'angry'] as const
const LABEL = { calm: '平稳', dissatisfied: '不满', angry: '激烈' }
const HEIGHT = [5, 12, 20]

/** 风险队列行内迷你声纹：消费者每条一柱（按情绪档位），客服/AI 连续回复为一个金点。 */
export function RiskSpark({ seq, width = 132 }: { seq?: string[]; width?: number }) {
  if (!seq?.length) return null
  const step = width / seq.length
  const counts = { calm: 0, dissatisfied: 0, angry: 0 }
  const marks = seq.map((token, i) => {
    const x = i * step + step / 2
    if (token === 'o') return <circle key={i} cx={x} cy={20} r={2} className="is-service" />
    const level = Number(token.slice(1)) || 0
    const name = LEVELS[Math.min(2, Math.max(0, level))]
    counts[name] += 1
    const h = HEIGHT[LEVELS.indexOf(name)]
    return <rect key={i} x={x - 2.5} y={23 - h} width={5} height={h} rx={2} className={`is-${name}`} />
  })
  const label = LEVELS.filter((name) => counts[name]).map((name) => LABEL[name]).join('、')
  const summary = LEVELS.every((name) => counts[name] === counts[LEVELS[0]]) && counts.calm
    ? `${label}各 ${counts.calm} 次`
    : LEVELS.filter((name) => counts[name]).map((name) => `${LABEL[name]} ${counts[name]} 次`).join('、')
  return <svg className="yt-rspark" width={width} height={26} viewBox={`0 0 ${width} 26`} role="img" aria-label={`情绪序列：${summary}`}>{marks}</svg>
}
