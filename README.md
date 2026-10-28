# 货眼 HuoYan

本地运行的购物研究助手，通过 Node.js、Python、Playwright 和 MCP 读取浏览器中实际加载的商品、SKU、店铺、评价及图片信息，保存可追溯的本地研究记录。

## 功能

- 商品搜索、筛选、排序、详情与准确 SKU 选择。
- 店内搜索、商品证据、图片概览和本地收藏。
- 淘宝账号收藏、旺旺会话列表及切换。
- 商家开票询问：准备草稿，核对授权后单次发送并读取回复。
- 标签复用、数量上限、工作流状态与重复发送保护。
- MCP、命令行和本地 Web 入口。

主要面向 Windows 和 Google Chrome。淘宝/天猫研究接口较完整，其他站点适配器的能力不同。平台页面变化可能导致接口失效；本地测试不证明所有实站模板兼容。

## 安装

需要 Node.js 18+、Python 和已安装的 Google Chrome。以下命令在项目目录的 PowerShell 中执行：

```powershell
npm ci
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm run chrome:cdp
```

在货眼专用 Chrome 窗口手动登录并打开目标平台。启动脚本默认使用本机回环地址的 9222 端口，浏览器资料存于当前用户的 LOCALAPPDATA/HuoYan 下。Python/MCP 默认连接此专用会话。不要将调试端口暴露到公网。

## 使用

```powershell
npm run check
.\.venv\Scripts\python.exe huoyan.py --help
npm run mcp
npm run web
# Node 采集入口显式指定与启动脚本相同的端口
node src/cli.js collect --site auto --keyword "电阻" --cdp http://127.0.0.1:9222
```

MCP 客户端配置示例；将路径替换为你自己的绝对路径：

```json
{"mcpServers":{"huoyan":{"command":"node","args":["C:/path/to/huoyan/src/mcp.js"]}}}
```

详细流程见 [多步工作流](docs/多步工作流操作手册.md)、[商家沟通](docs/商家发票沟通操作手册.md)、[店铺研究](docs/店铺操作手册.md)、[收藏](docs/双收藏与快速找回手册.md)和 [聊天列表](docs/聊天列表与会话切换手册.md)。手册中的示例标识符须替换为当前页面返回值；历史任务描述不构成当前用户授权。

## 可选话术模型

默认本地模板可独立使用。如需豆包改写，复制 .env.example 为 .env 并填写自己的配置；密钥仅存本地，不提交 Git。模型可用性和费用取决于自己的账号。详见 [话术改写](docs/豆包商家话术改写手册.md)。

## 验证

```powershell
npm test
npm run test:python
npm run test:chat
npm run test:inbox
npm run test:state
npm run test:research:mcp
```

浏览器测试使用隔离夹具，部分测试需要本机 Chrome 和可见桌面。不要连接私人购物会话执行测试。

## 隐私与使用边界

运行数据保存在本地 data/、output/ 等目录，默认不提交。发布副本不含原始浏览器配置、Cookie、密钥、真实聊天记录、采购资料、实测截图或旧 Git 历史。遇登录、验证码及异常访问停止；商家消息和账号操作须有相应用户授权，发送结果不明时先核对，避免重复执行。

## 许可

采用 [MIT License](LICENSE)。Copyright (c) 2026 liang4243。
