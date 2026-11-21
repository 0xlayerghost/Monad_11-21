# Monad 链证：黑客松提交材料

| 字段 | 内容 |
| --- | --- |
| 项目名称 | Monad 链证 |
| 前端演示地址 | https://monad-onchain-investigation.vercel.app/ |
| GitHub 仓库 | https://github.com/0xlayerghost/Monad_11-21 |
| 关联活动 | 待确认：提交前在活动平台选择准确的活动 |
| 功能截图 | [真实测试网调查截图](assets/monad-lianzheng-investigation.png)；提交平台需上传此图 |

## 项目描述

Monad 链证是一个面向 Monad 测试网的只读链上调查工作台。用户输入明确的地址、
代币或交易问题，Agent 通过受限工具查询链上事实，返回可追溯的区块、交易证据，
并展示工具调用过程。它支持原生币与指定 ERC-20 余额、指定授权额度、有限区块范围内的
Transfer 日志和单笔交易回执；每次查询都会核验网络身份，并保留查询范围与失败状态。

除了网页，项目还提供 CLI Skill 和只读 HTTP 接口，让其他获得访问权限的 Agent
复用同一套事实查询能力。结果区分已查到的事实、未知信息和推测；RPC 失败不会被说成
“余额为零”或“没有交易”。项目不扫描完整地址历史、不做价格预测，也不签名或执行交易。

## 演示建议

1. 打开前端，输入一个已知 Monad 测试网交易哈希，展示回答和工具调用记录。
2. 用另一个 Agent 按 Skill 调用 `list` 和 `call` CLI，核对同一笔回执的 chain ID、区块号和 hash。
3. 展示一次缺少参数的追问，以及一次超出能力范围的请求如何被准确说明。

固定、已核验的公开查询输入在
[测试网样本](skills/onchain-investigation/references/monad-testnet-samples.json)。
提交前重新运行查询并核对实时结果；不要用样本中的历史预期值冒充本次查询。
当前远程 HTTP 接口尚无内置公网鉴权与限流，不能宣称 Agent Hub 自动发现或公网 Agent
调用已经完成验收。
