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
  Row, Col, Alert, Result, Spin, message
} from 'antd'
import {
  FolderOpenOutlined, VideoCameraOutlined, SoundOutlined,
  ThunderboltOutlined, CheckCircleOutlined, RocketOutlined
} from '@ant-design/icons'

import { dialogApi, workerApi, configApi } from '../api/client'
import type { Platform, Style, Provider, JobOptions } from '../../electron/types'

const { Title, Text, Paragraph } = Typography

const PLATFORMS: { id: Platform; name: string; desc: string; ratio: string }[] = [
  { id: 'douyin', name: '抖音', desc: '竖屏 9:16', ratio: '1080×1920' },
  { id: 'xhs', name: '小红书', desc: '竖屏 9:16', ratio: '1080×1920' },
  { id: 'videohao', name: '视频号', desc: '竖屏 9:16', ratio: '1080×1920' },
  { id: 'general', name: '通用横屏', desc: '横屏 16:9', ratio: '1920×1080' }
]

const STYLES: { id: Style; name: string; desc: string }[] = [
  { id: 'fast_cut', name: '快剪', desc: '快速切换，节奏感强' },
  { id: 'ambiance', name: '氛围', desc: '慢节奏，情绪化' },
  { id: 'narrative', name: '叙事', desc: '故事线，按拍摄顺序' }
]

export default function NewJob() {
  const nav = useNavigate()
  const [step, setStep] = useState(0)
  const [input, setInput] = useState('')
  const [platform, setPlatform] = useState<Platform>('douyin')
  const [style, setStyle] = useState<Style>('fast_cut')
  const [duration, setDuration] = useState(30)
  const [bgm, setBgm] = useState('')
  const [provider, setProvider] = useState<Provider>('qwen-vl')
  const [apiReady, setApiReady] = useState<Record<Provider, boolean>>({
    'qwen-vl': false,
    doubao: false
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
    setApiReady({
      'qwen-vl': !!cfg.provider_keys['qwen-vl']?.key,
      doubao: !!cfg.provider_keys['doubao']?.key
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
        provider
      }
      if (bgm) opts.bgm = bgm
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
              <Row><Col span={6}><Text type="secondary">BGM</Text></Col><Col>{bgm || '默认'}</Col></Row>
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
                    字节豆包
                    {apiReady['doubao']
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
