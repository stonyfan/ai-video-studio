# AI 视频智能剪辑

> 让 AI 像导演一样"看懂"素材，自动剪出精彩短视频

## 当前阶段

**阶段 0：现有原型整理**（已完成）

下一阶段：阶段 1（Python 视频 worker 标准化）

详见 [docs/项目商品化开发计划书.md](docs/项目商品化开发计划书.md)

## 项目结构

```
ai-video-studio/
├── README.md                   本文件
├── .gitignore
├── requirements.txt            Python 依赖
├── docs/                       设计文档、流程文档、商业分析
├── legacy/                     已验证的原型脚本（按子项目组织）
│   ├── dao2/                   檀道2 项目（v1-v6 演进）
│   ├── yulan/                  玉兰花马天尼项目（多平台输出）
│   └── tools/                  通用工具（md2pdf 等）
├── video_worker/               阶段 1 待填：标准化 Python 视频 worker
├── configs/                    阶段 2 待填：模型/prompt/平台配置
├── tests/                      阶段 1 待填：单元 + 集成 + e2e 测试
├── samples/                    小型示例素材（自带）
└── outputs/                    生成物（.gitignore）
```

## 已验证的能力

- 多段素材自动合并、统一方向（竖屏/横屏）
- 视频稳定（vidstab）
- 场景切分（PySceneDetect）
- AI 视觉理解（每段内容、动作、物体、景别）
- 三联图高光瞬时检测（核心独创）
- 故事弧编排（按拍摄时序）
- 多平台差异化输出（抖音 15s / 小红书 30s / 视频号 30s）
- 冷调/暖调/自然色调、字幕烧入、BGM 节拍对齐

## 环境准备

### 系统要求

- Windows 10/11
- Python 3.10+
- FFmpeg（含 ffprobe，PATH 可用或放置在 worker 工作目录）

### 安装依赖

```bash
cd D:\ai-video-studio
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### FFmpeg 准备

方案 A（推荐）：将 `ffmpeg.exe` 和 `ffprobe.exe` 放到 `tools/` 子目录。
方案 B：将 FFmpeg 安装路径加入系统 PATH。

## 复现 demo（基于 legacy 脚本）

### Demo 1：檀道2 单平台输出（30 秒精华）

```bash
cd legacy/dao2

# 1. 准备素材：将 37 段 4K 视频（共约 5GB）放到 source/ 子目录
#    （来源：用户私有，不放仓库）

# 2. 重编码 + 稳定 + 场景切分 + 三联图 + 高光检测 + 编排 + 渲染
python scene_split.py
python make_triplets.py
python build_v6.py
```

输入：37 段 4K 手机视频
输出：`final_dao2_v6.mp4`（30 秒精华版）

### Demo 2：玉兰花马天尼多平台输出

```bash
cd legacy/yulan

# 1. 准备素材：将 19 段 4K 视频放到 D:\BaiduNetdiskDownload\玉兰花马丁尼\
#    或修改 prep.py 的 SRC_DIR 路径

# 2. 多平台一次性输出
python prep.py            # 标准化
python scene_split.py     # 场景切分
python make_triplets.py   # 三联图
python detect_beats.py    # BGM 节拍
python multi_build.py --all  # 3 个平台同时构建
```

输出：
- `final_玉兰马丁尼_抖音15s.mp4`（极限快剪）
- `final_玉兰马丁尼_小红书30s.mp4`（暖调氛围）
- `final_玉兰马丁尼_视频号30s.mp4`（自然叙事）

## AI 视觉模型

当前原型用 `mcp__zai-mcp-server__analyze_image`（zai 视觉 API）。

阶段 2 将接入多 provider 适配层：
- Qwen-VL-Plus（阿里，性价比首选）
- Doubao-vision-pro（字节，最便宜）
- GLM-4V-Plus（智谱）

API key 由后端代理，不进客户端代码。

## 文档

- [商品化开发计划书](docs/项目商品化开发计划书.md) - 全路线
- [项目总结与服务化分析](docs/项目总结与服务化分析.md) - 技术复盘
- [产品介绍](docs/产品介绍.md) - 面向客户
- [Prompt 模板库](docs/Prompt模板库.md) - AI prompt 工程

## License

私有，未公开授权。
