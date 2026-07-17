/**
 * 新建任务向导（5 步）
 *
 * Step 1: 选素材（文件夹拖拽 + 浏览）
 * Step 2: 选平台（4 卡片）
 * Step 3: 选风格（3 单选）
 * Step 4: 时长 + BGM（滑块 + 文件选择）
 * Step 5: Provider + API key 检查 + 启动
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Steps, Button, Space, Input, Typography, Tag, Radio, Slider,
  Row, Col, Alert, Result, Spin, App, Segmented, InputNumber
} from 'antd'
import {
  FolderOpenOutlined, VideoCameraOutlined, SoundOutlined,
  ThunderboltOutlined, CheckCircleOutlined, RocketOutlined, CopyOutlined
} from '@ant-design/icons'

import { dialogApi, workerApi, configApi } from '../api/client'
import type { Platform, Style, Provider, JobOptions, OrchestrationMode } from '../../electron/types'

const { Title, Text, Paragraph } = Typography

const PLATFORMS: { id: Platform; name: string; desc: string; ratio: string }[] = [
  { id: 'douyin', name: '抖音', desc: '竖屏 9:16', ratio: '1080×1920' },
  { id: 'xhs', name: '小红书', desc: '竖屏 9:16', ratio: '1080×1920' },
  { id: 'videohao', name: '视频号', desc: '竖屏 9:16', ratio: '1080×1920' },
  { id: 'general', name: '通用横屏', desc: '横屏 16:9', ratio: '1920×1080' }
]

const STYLES: { id: Style; name: string; desc: string }[] = [
  { id: 'ambiance', name: '氛围', desc: '慢节奏，情绪化' },
  { id: 'narrative', name: '叙事', desc: '故事线，按拍摄顺序' }
]

export default function NewJob() {
  const nav = useNavigate()
  const { message } = App.useApp()
  const [step, setStep] = useState(0)
  const [input, setInput] = useState('')
  const [platform, setPlatform] = useState<Platform>('douyin')
  const [style, setStyle] = useState<Style>('narrative')
  const [duration, setDuration] = useState(30)
  const [variants, setVariants] = useState(1)
  const [bgm, setBgm] = useState('')
  const [provider, setProvider] = useState<Provider>('qwen-vl')
  const [orchestrationMode, setOrchestrationMode] = useState<OrchestrationMode>('default')
  const [skill, setSkill] = useState<string>('auto')
  const [apiReady, setApiReady] = useState<Record<Provider, boolean>>({
    'qwen-vl': false,
    doubao: false,
    'doubao-agent-plan': false,
    glm: false
  })
  const [starting, setStarting] = useState(false)

  const chooseInput = async () => {
    const dir = await dialogApi.chooseFolder()
    if (dir) setInput(dir)
  }

  const chooseBgm = async () => {
    // 复用 chooseFolder 不太合适；这里先用输入框
    // TODO: 后续加 chooseFile IPC
    message.info('BGM 路径请手动输入（后续版本会加文件选择）')
  }

  const checkProviderKey = async () => {
    const cfg = await configApi.getAll()
    const ready: Record<Provider, boolean> = {
      'qwen-vl': !!cfg.provider_keys['qwen-vl']?.key,
      doubao: !!cfg.provider_keys['doubao']?.key,
      'doubao-agent-plan': !!cfg.provider_keys['doubao-agent-plan']?.key,
      glm: !!cfg.provider_keys['glm']?.key
    }
    setApiReady(ready)
    // 当前 provider 未配置时，自动切到第一个已配置的（qwen-vl → doubao → doubao-agent-plan → glm）
    setProvider(prev => {
      if (ready[prev]) return prev
      if (ready['qwen-vl']) return 'qwen-vl'
      if (ready.doubao) return 'doubao'
      if (ready['doubao-agent-plan']) return 'doubao-agent-plan'
      if (ready.glm) return 'glm'
      return prev
    })
  }

  // 进入 Step 5 时检查 API key
  const handleStepChange = async (next: number) => {
    if (next === 4) await checkProviderKey()
    setStep(next)
  }

  const start = async () => {
    if (!apiReady[provider]) {
      message.error(`${provider} 的 API key 未配置，请到设置页配置`)
      return
    }
    setStarting(true)
    try {
      const opts: JobOptions = {
        input,
        platform,
        style,
        duration,
        provider,
        orchestration_mode: orchestrationMode,
        skill,
      }
      if (bgm) opts.bgm = bgm
      if (variants > 1) opts.variants = variants
      const result = await workerApi.startJob(opts) as
        { ok: true; handle: { jobId: string; pid: number } } |
        { ok: false; error: string }
      if (!result.ok) {
        message.error(`启动失败: ${result.error}`)
        return
      }
      message.success(`任务已启动: ${result.handle.jobId}`)
      nav(`/jobs/${result.handle.jobId}`)
    } catch (e) {
      message.error(`启动异常: ${(e as Error).message}`)
    } finally {
      setStarting(false)
    }
  }

  const steps = [
    {
      title: '选素材',
      icon: <FolderOpenOutlined />,
      content: (
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <Paragraph type="secondary">
            选择包含视频素材的文件夹。worker 会递归扫描所有 <Text code>.mp4 / .mov / .avi</Text> 文件。
          </Paragraph>
          <Input.Search
            placeholder="点右侧按钮选文件夹"
            value={input}
            enterButton="浏览"
            size="large"
            readOnly
            onSearch={chooseInput}
          />
          {input && (
            <Alert
              type="info"
              message={`已选: ${input}`}
              description="worker 会自动识别横屏/竖屏，必要时做模糊背景适配"
              showIcon
            />
          )}
        </Space>
      )
    },
    {
      title: '平台',
      icon: <VideoCameraOutlined />,
      content: (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Paragraph type="secondary">不同平台对分辨率/BGM 有不同优化</Paragraph>
          <Row gutter={[16, 16]}>
            {PLATFORMS.map(p => (
              <Col span={6} key={p.id}>
                <Card
                  hoverable
                  size="small"
                  onClick={() => setPlatform(p.id)}
                  style={{
                    borderColor: platform === p.id ? '#1677ff' : '#f0f0f0',
                    borderWidth: 2,
                    background: platform === p.id ? '#e6f4ff' : '#fff'
                  }}
                >
                  <Title level={5} style={{ margin: 0 }}>{p.name}</Title>
                  <Text type="secondary">{p.desc}</Text>
                  <br />
                  <Text code>{p.ratio}</Text>
                </Card>
              </Col>
            ))}
          </Row>
        </Space>
      )
    },
    {
      title: '风格',
      icon: <ThunderboltOutlined />,
      content: (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Paragraph type="secondary">不同风格对应不同的剪辑参数（切镜频率、转场、节奏）</Paragraph>
          <Radio.Group value={style} onChange={e => setStyle(e.target.value)}>
            <Space direction="vertical">
              {STYLES.map(s => (
                <Radio key={s.id} value={s.id}>
                  <Space>
                    <Text strong>{s.name}</Text>
                    <Text type="secondary">{s.desc}</Text>
                  </Space>
                </Radio>
              ))}
            </Space>
          </Radio.Group>
        </Space>
      )
    },
    {
      title: '时长 / BGM',
      icon: <SoundOutlined />,
      content: (
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <div>
            <Title level={5}>编排模式</Title>
            <Segmented
              value={orchestrationMode}
              onChange={v => setOrchestrationMode(v as OrchestrationMode)}
              options={[
                {
                  label: '默认',
                  value: 'default',
                  icon: <ThunderboltOutlined />,
                },
                {
                  label: '时间轴',
                  value: 'timeline',
                  icon: <ThunderboltOutlined />,
                },
                {
                  label: 'LLM 故事阶段',
                  value: 'llm',
                  icon: <VideoCameraOutlined />,
                },
              ]}
            />
            <Paragraph type="secondary" style={{ marginTop: 8, fontSize: 12 }}>
              {orchestrationMode === 'default'
                ? 'LLM 挑选（每阶段代表+高分填充）+ per-src 去重 + creation_time 时间序。混合策略，推荐。'
                : orchestrationMode === 'timeline'
                ? '按视频真实拍摄时间（creation_time）排序，纯算法截断。快速、可预测。'
                : '在时间序基础上调用 LLM 把片段聚成故事阶段，每阶段取代表 + 高分填充，按阶段序输出。LLM 调用 10-30s。'}
            </Paragraph>
          </div>
          <div>
            <Title level={5}>Skill（剪辑技能）</Title>
            <Segmented
              value={skill}
              onChange={v => setSkill(v as string)}
              options={[
                { label: '自动匹配', value: 'auto' },
                { label: '不使用', value: 'none' },
                { label: '调酒', value: 'cocktail-mixology' },
              ]}
            />
            <Paragraph type="secondary" style={{ marginTop: 8, fontSize: 12 }}>
              {skill === 'auto'
                ? '根据画面内容（main_objects/action_type 命中率）自动选择 skill。无匹配时退回纯算法。'
                : skill === 'none'
                ? '不注入任何 skill 指导，纯靠 LLM 自由发挥。'
                : '调酒类素材专用：HOOK→SETUP→BUILD→GARNISH→SERVE 五段式骨架，T1 优先级（倒酒/摇晃/特写）。'}
            </Paragraph>
          </div>
          <div>
            <Title level={5}>目标时长</Title>
            <Slider
              min={5} max={300} step={5}
              value={duration}
              onChange={v => setDuration(v)}
              marks={{
                5: '5s', 15: '15s', 30: '30s', 60: '1min',
                120: '2min', 180: '3min', 300: '5min'
              }}
            />
            <Text strong style={{ fontSize: 18 }}>{duration} 秒</Text>
          </div>
          <div>
            <Title level={5}>
              <Space>
                生成数量
                <CopyOutlined />
              </Space>
            </Title>
            <Space>
              <InputNumber
                min={1} max={10} value={variants}
                onChange={v => setVariants(typeof v === 'number' ? v : 1)}
                size="large"
              />
              <Text type="secondary">个视频</Text>
            </Space>
            <Paragraph type="secondary" style={{ marginTop: 8, fontSize: 12 }}>
              一次任务生成 N 个 30s 变体。视觉分析只跑一次，复用结果循环 LLM+渲染 N 次。
              N&gt;1 时每个变体注入不同风格 hint（动作密集 / 氛围慢剪 / 故事推进 等），产出差异化成片。
            </Paragraph>
          </div>
          <div>
            <Title level={5}>BGM（可选）</Title>
            <Input.Search
              placeholder="BGM 文件路径（留空使用平台默认）"
              value={bgm}
              onChange={e => setBgm(e.target.value)}
              enterButton="浏览"
              onSearch={chooseBgm}
            />
          </div>
        </Space>
      )
    },
    {
      title: '启动',
      icon: <RocketOutlined />,
      content: (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Paragraph type="secondary">最后确认参数，点击启动开始任务</Paragraph>
          <Card size="small">
            <Space direction="vertical" style={{ width: '100%' }}>
              <Row><Col span={6}><Text type="secondary">素材目录</Text></Col><Col>{input || '-'}</Col></Row>
              <Row><Col span={6}><Text type="secondary">平台</Text></Col><Col>
                <Tag color="blue">{PLATFORMS.find(p => p.id === platform)?.name}</Tag>
              </Col></Row>
              <Row><Col span={6}><Text type="secondary">风格</Text></Col><Col>
                <Tag color="purple">{STYLES.find(s => s.id === style)?.name}</Tag>
              </Col></Row>
              <Row><Col span={6}><Text type="secondary">时长</Text></Col><Col>{duration} 秒</Col></Row>
              <Row><Col span={6}><Text type="secondary">生成数量</Text></Col><Col>
                <Tag color="magenta">{variants} 个</Tag>
                {variants > 1 && <Text type="secondary" style={{ marginLeft: 8 }}>视觉复用，LLM+渲染循环 {variants} 次</Text>}
              </Col></Row>
              <Row><Col span={6}><Text type="secondary">编排</Text></Col><Col>
                <Tag color="cyan">{
                  orchestrationMode === 'default' ? '默认' :
                  orchestrationMode === 'timeline' ? '时间轴' : 'LLM 故事阶段'
                }</Tag>
              </Col></Row>
              <Row><Col span={6}><Text type="secondary">BGM</Text></Col><Col>{bgm || '默认'}</Col></Row>
              <Row><Col span={6}><Text type="secondary">Skill</Text></Col><Col>
                <Tag color="orange">{
                  skill === 'auto' ? '自动匹配' :
                  skill === 'none' ? '不使用' :
                  skill === 'cocktail-mixology' ? '调酒' : skill
                }</Tag>
              </Col></Row>
            </Space>
          </Card>
          <div>
            <Title level={5}>AI 视觉分析 Provider</Title>
            <Radio.Group value={provider} onChange={e => setProvider(e.target.value)}>
              <Space direction="vertical">
                <Radio value="qwen-vl">
                  <Space>
                    阿里 Qwen-VL
                    {apiReady['qwen-vl']
                      ? <Tag color="green" icon={<CheckCircleOutlined />}>已配置</Tag>
                      : <Tag color="red" onClick={() => nav('/settings')}>未配置（点这里去设置）</Tag>}
                  </Space>
                </Radio>
                <Radio value="doubao">
                  <Space>
                    字节豆包（按量）
                    {apiReady['doubao']
                      ? <Tag color="green" icon={<CheckCircleOutlined />}>已配置</Tag>
                      : <Tag color="red" onClick={() => nav('/settings')}>未配置（点这里去设置）</Tag>}
                  </Space>
                </Radio>
                <Radio value="doubao-agent-plan">
                  <Space>
                    字节豆包 Agent Plan（订阅套餐）
                    {apiReady['doubao-agent-plan']
                      ? <Tag color="green" icon={<CheckCircleOutlined />}>已配置</Tag>
                      : <Tag color="red" onClick={() => nav('/settings')}>未配置（点这里去设置）</Tag>}
                  </Space>
                </Radio>
                <Radio value="glm">
                  <Space>
                    智谱 GLM-4V
                    {apiReady['glm']
                      ? <Tag color="green" icon={<CheckCircleOutlined />}>已配置</Tag>
                      : <Tag color="red" onClick={() => nav('/settings')}>未配置（点这里去设置）</Tag>}
                  </Space>
                </Radio>
              </Space>
            </Radio.Group>
          </div>
          {starting && (
            <Result
              icon={<Spin />}
              title="正在启动 worker 进程..."
            />
          )}
        </Space>
      )
    }
  ]

  return (
    <Card>
      <Steps current={step} items={steps.map(s => ({ title: s.title, icon: s.icon }))} />
      <div style={{ marginTop: 32, minHeight: 280 }}>
        {steps[step].content}
      </div>
      <div style={{ marginTop: 24, display: 'flex', justifyContent: 'space-between' }}>
        <Button disabled={step === 0 || starting} onClick={() => handleStepChange(step - 1)}>
          上一步
        </Button>
        {step < steps.length - 1 ? (
          <Button type="primary" disabled={step === 0 && !input}
                  onClick={() => handleStepChange(step + 1)}>
            下一步
          </Button>
        ) : (
          <Button type="primary" size="large" icon={<RocketOutlined />}
                  loading={starting} disabled={!apiReady[provider]} onClick={start}>
            启动任务
          </Button>
        )}
      </div>
    </Card>
  )
}
