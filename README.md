# 监管物资保管服务

该项目为监管仓、证物室和受控物资保管点提供服务端 API，覆盖人员授权、物资分类、批次登记、收发记录、审批、预警、审计日志与统计报表。数据保存在 SQLite，所有测试和接口验收均可在单个 Linux 应用容器内离线完成。

## 运行环境

- Python 3.11
- Django REST Framework
- SQLite

## 安装与初始化

```bash
python -m pip install -r backend/requirements.txt
cd backend
python manage.py migrate --run-syncdb
```

## 到场预约

集中移交场景下，移交单位可提前创建到场预约，值班员按预约签到接收，全程保留轨迹。

- `GET/POST /api/appointments/` 预约列表/创建（声明时间窗、预估件数、交接人员；移交单位用户仅见本单位预约）
- `GET /api/appointments/today/` 当日到场预约（值班员签到台）
- `GET /api/appointments/{id}/` 预约详情（含交接人员、签到记录、轨迹、入库记录）
- `POST /api/appointments/{id}/reschedule/` 预约改期（记录新旧时间窗与原因）
- `POST /api/appointments/{id}/cancel/` 取消预约
- `POST /api/appointments/{id}/check-in/` 值班员签到：核对身份与实际件数，决定接收/部分接收/拒收；自动判定准时/提前/迟到，重复签到被拦截并留痕

接收或部分接收时自动生成正式入库记录（`StockIn.appointment` 关联预约，备注含预估/实到/接收差异），可通过 `GET /api/stock-in/?appointment_id={id}` 追溯。

## 测试

```bash
cd backend
pytest -q
```

## 编译检查

```bash
python -m compileall -q backend
```

## API 验收

```bash
cd backend
python manage.py migrate --run-syncdb
python manage.py shell -c "from rest_framework.test import APIClient; from apps.authentication.models import User; u=User.objects.create_user('smoke','safe-pass',role='admin'); c=APIClient(); r=c.post('/api/auth/login/',{'username':'smoke','password':'safe-pass'},format='json'); print(r.status_code, bool(r.json()['data']['token']))"
```

## 容器

```bash
docker build -t custody-service .
docker run --rm custody-service
```
