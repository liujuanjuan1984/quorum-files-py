# quorum-files-py

## 原理

在多台服务器上，部署了多个不同的小型服务，每个服务都有一些数据需要备份：有些数据仅需一次性加密备份，有些数据需要定期多重备份。

这个 repo 就是满足这个需求的。

所采用的实现方案是：

1、采用 quorum 的分布式网络，使用 blockchain of public group （下文简称 blockchain）来存储需要加密备份的数据，并自动实现异地多重备份。

2、客户端（需要定期备份数据的终端服务器）采用 hybird 对数据加密后，如果数据超过 300kb 则切片，然后通过 api 发送到 blockchain 上出块。

3、从 blockchain 还原数据，就是遍历 blockchain 获取切片后的数据，将之合并再解密为原始文件数据。

## 使用

### 初始化

准备 pulic group，设置好白名单权限。包含三类角色：

#### owner-fullnode：出块节点

1、创建 pulic group（group_files 类型），得到 seed
2、设置该 group 的 POST auth 为白名单模式（仅有白名单内的密钥有权往链上写入数据）

#### user-fullnodes：异地自动备份节点（最好2个及以上，分布于不同的机器）

1、使用 owner 所提供的 seed 加入指定 group
2、生成指定 group 的 role 为 node 的 jwt，作为 lightnode 与 blockchain 交互的数据接口

#### clients-lightnodes: 客户端（需要定期备份数据的终端服务器）

1、每个终端生成至少一对密钥对，把公钥发给 owner 添加到 group 的白名单内
2、每个终端生成数个数据加密解密用的密钥，并通过第三方工具备份保管（比如 1password）

### 部署使用

安装依赖：

```sh
pip install officy
pip install git+https://github.com/liujuanjuan1984/quorum-data-py.git
pip install git+https://github.com/liujuanjuan1984/quorum-mininode-py.git
pip install git+https://github.com/nodewee/mixin-sdk-python.git
```

执行脚本：

每个终端，按需修改 `file_bot.py` 中的 config 信息，并设定 tasks 任务（支持一次性备份，和每日备份一次）。定时重启该脚本，将自动持续执行。

该脚本支持：

1、上传备份：把 file 加密并切片后，发送到 group 存储

终端使用本服务，采用密钥加密文件后，把文件切块，通过 lightnode api 发送到 group 出块。每个终端都需记录所需出块的 trxs 数据，直到所有 trxs 出块成功后，把该文件的切换信息及 trx_ids 构建一个概述 trx 到 group 出块成功。

2、下载还原：遍历 group 数据，获取概述 trx，并通过概述 trx 拿到相应的 trxs，把数据切片还原为 file 再解密。

3、服务监控：通过 mixin bot 监控 fullnode 的状态，以及同步每次备份/还原的 log，以及时发现异常。

