# 专栏续读风险试算

分类与阈值选择的真实业务分析小型项目。完整模拟客户、痛点、上下游、算法公式与一天工作剧本见 [BUSINESS.md](BUSINESS.md)。

## 模块与业务流程
数据接入（JSON/CSV、字段验证、批次指纹）→ 参数化分析（异步 Python worker）→ 结果复核（指标、图形、明细、解释、批准）→ 定时分发（本地收件箱、CSV/JSON、SHA256）；另有业务总览和审计轨迹。
三个贯穿全栈的实体：Dataset 数据批次、Job 分析任务、Report 分发计划；辅助 User、Audit、Delivery。

## 阅读事件分批接入（防止到期后阅读泄漏）
「事件批次」页支持按批接入带事件号、读者、会话、期号、发生时间、完成率的阅读记录，以及带到期日的读者名册。
- 事件号全局唯一：同号同内容判为重复投递、不多计；同号异内容整批拒绝（原子事务，不写任何一行）。
- 按读者到期前14日窗口自动生成试验批次，每批固定 `cutoff_receive_no`（截至哪次接收）；迟到记录不回写已就绪批次，同窗口在截止点后收到成员新事件时自动新建更高截止点的版本批次（第2版、第3版……），旧批次保持不可变。
- 窗口内口径：访问按会话去重；完成率按各期末次记录取平均；未读天数按末次访问距窗口末日；已读期数按期号去重；到期当日及之后事件排除。
- 批次构建按窗口独立提交并持久化 building 标记，中断后由 worker tick 或「恢复/补建」按钮重入：清理半成品台账后重建，截止点不漂移；仅 ready 批次产出不可变汇总样本（标准 Dataset），building 不供试验使用。
- 批次台账逐事件记录纳入/排除与原因，页面可筛选，支持 CSV/JSON 下载追溯到原事件号；所有接入、构建动作进入审计。
- 原汇总样本导入（「数据接入」页）保持不变，与事件批次产出的 Dataset 共用分析、批准与分发流程。
- 接口前缀 `/intake`：`/roster`、`/events`、`/runs`、`/batches`、`/batches/{id}`、`/batches/{id}/ledger?format=csv|json`、`/batches/build`；写操作需 admin/analyst，读取与下载 viewer 可用。
- 独立单元测试在 test-artifacts/gb-1008/tests/（test_intake.py 口径测试、test_intake_api.py 路由冒烟），运行方式见各文件头部。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18207；后端文档 http://localhost:19207/docs；数据库宿主端口 17707。
`SEED_DEMO=true` 自动幂等 seed；不覆盖用户修改。手动 seed 命令可重复执行。

## 演示账号与权限
|账号|密码|真实权限|
|---|---|---|
|admin@demo.local|Demo123!|接入、执行、批准、分发、暂停、读取与下载|
|analyst@demo.local|Demo123!|接入、执行、读取与下载；不能批准或安排分发|
|viewer@demo.local|Demo123!|只读与下载|

## 技术与本地开发
Python 3.12 / FastAPI / SQLAlchemy / NumPy / SciPy / scikit-learn；MySQL 8.0；Redis 7；Nginx；原生 HTML CSS JavaScript ES modules（用户指定）。后端所有校验、持久化和算法在服务端。无前端打包步骤。
后端：安装 backend/requirements.txt，设置 DATABASE_URL、REDIS_URL、JWT_SECRET、ARTIFACT_DIR 后在 backend/ 执行 `python -m migrations.initial`、`python -m scripts.seed_demo`、`uvicorn src.main:app`，另开 `python -m src.worker`。前端使用带 /api 反向代理的 Nginx，直接打开 index.html 不支持 API。

## 目录与工程约定
backend/src/{models,schemas,services,routes,controllers,middlewares,constants,config,utils}；backend/scripts/seed_demo.py；backend/migrations/initial.py。
frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。
Role 枚举：admin/analyst/viewer；JobStatus：queued/running/completed/failed。后端 backend/src/constants/enums.py，前端 frontend/src/constants/enums.js；路由权限在 middlewares/auth.py；页面按相同角色控制操作入口。

## 环境变量与 Docker
COMPOSE_PROJECT_NAME=reader-risk；FRONTEND_PORT=18207；BACKEND_PORT=19207；DB_PORT=17707；DB_PASSWORD、JWT_SECRET 见 .env.example；SEED_DEMO 默认 true。共享命名产物卷供后端下载与 worker 写入，数据库/Redis 各持久卷。
恰好五服务均有健康检查。Redis 队列加 SQL 排队状态兜底；worker 按 next_run 生成本地收件箱文件。周期 60 秒至 30 天。分发结果为批准分析的固定快照；若需新数据重新计算并建立新计划。当前不连接邮件或企业聊天。
错误响应、请求编号、Redis 每 IP 每分钟 240 次限流、JWT 和数据库操作审计。演示密钥与密码仅供本机模拟；生产部署前配置独立密钥与账号。

## 数据与验收
所有数据为固定随机种子生成的模拟业务数据，不能作为实际生产决策证据。项目独立算法、输入边界及业务局限详见 BUSINESS.md。测试与截图统一存放 ../../test-artifacts/gb-1008/，源码不含日志/截图/测试报告。
清理本项目演示数据：`docker compose down -v --remove-orphans`（会删除本项目命名卷）。

## License
MIT，见 LICENSE。
