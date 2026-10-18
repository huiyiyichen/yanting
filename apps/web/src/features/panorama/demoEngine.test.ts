import { describe, expect, it } from 'vitest'
import { PanoramaDemo } from './demoEngine'

/**
 * 用户反馈 10-18 #7：全景做示例稿那样的演示。
 * D1 演示开始就有三条泳道的会话；D2 推进后 AI 会处理并回复、新会话进线；
 * D3 激烈/就医消息转待人工后会被接管；D4 并行组步骤同时进行。
 */
describe('PanoramaDemo', () => {
  const seeded = () => { let x = 7; return () => ((x = (x * 9301 + 49297) % 233280) / 233280) }
  it('D1 初始三泳道都有会话', () => {
    const lanes = new Set(new PanoramaDemo(seeded(), 0).view().items.map((i) => i.lane))
    expect([...lanes].sort()).toEqual(['ai', 'human', 'wait'])
  })
  it('D2-D4 推进后有回复、并行步骤、转人工与接管', () => {
    const sim = new PanoramaDemo(seeded(), 0)
    let parallel = false
    const seen = new Set<string>()
    const before = sim.messages('S00059').length
    for (let t = 0; t < 180_000; t += 200) {
      sim.tick(200)
      sim.view().items.forEach((i) => seen.add(i.conversationId))
      const running = sim.view().items.flatMap((i) => i.currentRun?.steps ?? [])
      if (running.filter((s) => s.group && s.status === 'active').length > 1) parallel = true
    }
    expect(parallel).toBe(true)
    const items = sim.view().items
    expect(seen.has('S00058')).toBe(true)
    expect(sim.messages('S00059').length).toBeGreaterThan(before)
    expect(items.find((i) => i.conversationId === 'S00015')?.lane).toBe('human')
  })
  it('手动接管进入人工处理中', () => {
    const sim = new PanoramaDemo(seeded(), 0)
    sim.takeover('S00014')
    expect(sim.view().items.find((i) => i.conversationId === 'S00014')).toMatchObject({ lane: 'human', handler: 'G001' })
  })
})
