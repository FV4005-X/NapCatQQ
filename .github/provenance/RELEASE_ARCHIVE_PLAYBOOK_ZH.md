# NapCat 历史发行包核查与归档流程

> 本文只记录 NapCat 项目的历史版本核查、复刻和归档方法。它是维护文档，不属于 NapCat 程序本身。

## 1. 固定目标版本和源码

开始前先确定版本 Tag，并解析为完整的 40 位 Git Commit SHA。后续所有构建、对比和归档都以这个 Commit 为准，不使用可能变化的 `main` 或 `latest`。

本次目标为 NapCat `v4.18.42`：

```text
Source Commit: 9335843246e3b7a17944861f3ac8731a259732c2
```

历史发行包参考为 [XingYunStar/NapCatQQ v4.18.42](https://github.com/XingYunStar/NapCatQQ/releases/tag/v4.18.42)。应同时记录来源网址、文件名、文件大小、SHA256 和获取时间。多个归档来源相互一致可以增强证据，但如果它们可能复制自同一个上游，就不能当作完全独立的官方认证。

## 2. 分清不同层级的“一致”

| 核验内容 | 能说明什么 | 不能说明什么 |
| --- | --- | --- |
| 文件 SHA256 | 下载文件与指定参考文件字节一致 | 参考文件一定由官方发布 |
| 解压后逐文件 SHA256 | 文件内容、依赖和资源一致 | 压缩包元数据一致 |
| ZIP 完整 SHA256 | 整个 ZIP 的字节完全一致 | 发布者身份或构建过程可信 |
| Docker Image ID、RootFS DiffID | 镜像配置及解压后的文件系统内容一致 | Registry Manifest 和压缩层字节一致 |
| 官方签名或可信构建证明 | 可进一步验证发布来源 | 不代表软件没有漏洞 |

因此，完整性核验、内容一致性和来源认证应分别记录，不要混为一个“官方认证通过”。

## 3. 从源码构建并核对生产依赖

先阅读目标版本的 `.github/workflows/release-publish.yml`、`pnpm-lock.yaml`、各项目的 `package.json` 和构建脚本，确认原流程实际执行了什么。

NapCat v4.18.42 的原始发布流程在编译后，对 Framework 和 Shell 删除开发依赖声明，再执行 `npm install --omit=dev`。这一步会重新解析生产依赖；它并不等同于严格按 `pnpm-lock.yaml` 安装生产依赖。因此，即使源码 Tag 相同，隔一段时间构建也可能得到不同的第三方依赖版本。

本次复刻以历史发布包中的依赖版本为对照，核查关键依赖、运行时文件和完整目录内容。不能只看构建成功或 CI 绿色，还应比较实际安装版本和逐文件 SHA256。

## 4. ZIP 字节级复刻

当解压后的文件已经一致，ZIP 的 SHA256 仍可能不同。原因包括：

- 文件条目顺序；
- 文件时间戳、权限和创建平台标记；
- ZIP Extra Field、注释和目录条目；
- 压缩方式、压缩级别和压缩数据；
- Local Header、Central Directory 及偏移量。

本次复刻先独立构建程序文件和生产依赖，再读取历史 ZIP 中的文件顺序及必要元数据，使用固定工具重新打包。历史 ZIP 仅用于读取元数据和最终校验，不直接提供输出包中的程序文件或压缩数据。

三个 ZIP 的最终 SHA256：

| 文件 | SHA256 |
| --- | --- |
| `NapCat.Framework.zip` | `118d66bb4849b7fcec05a4cafc9e33ed44f9236d56661f7097aba2ab3081df2e` |
| `NapCat.Shell.zip` | `02e5ff0f79916c1e04c81c1b4590056406fb4293f1f1300c955e71fd08b2829d` |
| `NapCat.Shell.Windows.Node.zip` | `77397ac38d66f46383e48f08f35d5f9d37ec575c22069f62d6c600e73b4521ed` |

这次结果达到与历史参考 ZIP 的完整字节一致。需要准确描述其边界：它是利用历史包元数据完成的复刻，不代表仅凭源码和锁文件、完全不参考历史 ZIP 就能从零自举出同样的字节。

详细的文件来源、构建差异和复刻记录见 [v4.18.42 发布包来源说明](v4.18.42-release-provenance.md)。

## 5. Docker 镜像归档

本次没有从 Dockerfile 重新构建历史镜像，而是先核查历史归档文件，再将符合预期 SHA256 的 tar 保存到 NapCat v4.18.42 Release。

| 架构 | 文件大小 | SHA256 | 当前结论 |
| --- | ---: | --- | --- |
| amd64 | 612,216,320 字节 | `85e3fd02b58fd836a0177734b6ff77a896000bcfcf209b3b200d7e8b8452df7c` | 文件完整性、Docker 加载及镜像配置/RootFS 对照通过；未取得官方签名 |
| arm64 | 597,573,632 字节 | `0d14594844e9135c760e710754a8778d98649de2ca837fce5a61b69b7d39954d` | 文件完整性和 Docker 加载检查通过；缺少可访问的 Hub 镜像副本进行独立内容对照 |

Docker 归档的 SHA256 只能证明 tar 文件与所采用的参考文件相同。对于无法直接访问的 Registry Tag，应记录实际请求结果，不要把搜索缓存或第三方镜像页面当作当前仍可拉取的证明。

## 6. Release 更新前后的检查

1. 更新前记录现有 Release 的 Tag、说明、资产文件名、大小和 SHA256。
2. 上传前重新计算本地文件 SHA256；任何一项不匹配都停止发布。
3. 对已经存在的同名资产，只有确认摘要和大小相同才允许保留；不一致时拒绝覆盖。
4. 上传后再次读取 GitHub Release API，核对资产数量、大小和 `digest`。
5. 在 Release 说明中写清来源和证据边界，不把“文件完整性通过”表述成“官方身份认证通过”。
6. 保存来源说明和 Actions 执行记录，避免只依赖有保留期限的临时构建产物。

## 7. 仓库内相关文件

- `.github/workflows/release-publish.yml`：基于原有发布流程维护的手动构建工作流。
- `.github/workflows/verify-release-build.yml`：手动验证指定版本的构建、类型检查和测试。
- `.github/workflows/verify-docker-archives.yml`：检查历史 Docker tar 的完整性及可进行的镜像对照。
- `.github/workflows/restore-napcat-archive.yml`：按显式确认选项恢复历史 Tag 或发行资产。
- `.github/scripts/inspect-release-zip-metadata.py`：检查 ZIP 内部结构和元数据差异。
- `.github/scripts/replay-historical-zip-metadata.py`：根据历史 ZIP 元数据重新打包本地构建文件。
- `.github/provenance/v4.18.42-release-provenance.md`：记录本次发布包和 Docker 归档的详细核查结果。

**最终原则：固定源码版本，核查真实依赖，独立构建程序内容，严格比较 SHA256，记录证据边界；来源不明或校验不符的文件不得进入正式 Release。**
