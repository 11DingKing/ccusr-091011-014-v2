"""
到场预约测试
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from apps.warehouse.models import Category, Goods, StockIn, Unit, Variety
from .models import Appointment, CheckIn


class AppointmentFixture(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("duty-officer", "testpass123", role="admin")
        self.unit_user = User.objects.create_user("handover-user", "testpass123", role="user")
        self.other_user = User.objects.create_user("other-user", "testpass123", role="user")

        self.admin_client = APIClient()
        self.admin_client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.admin)}")
        self.user_client = APIClient()
        self.user_client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.unit_user)}")
        self.other_client = APIClient()
        self.other_client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.other_user)}")

        self.unit = Unit.objects.create(name="件", created_by=self.admin)
        self.category = Category.objects.create(name="受控器材", unit=self.unit, created_by=self.admin)
        self.variety = Variety.objects.create(name="记录终端", category=self.category, created_by=self.admin)
        self.goods = Goods.objects.create(
            variety=self.variety,
            name="执法记录终端",
            code="DEV-001",
            quantity=Decimal("12"),
            warning_threshold=Decimal("5"),
        )

    def appointment_payload(self, **overrides):
        start = timezone.now() + timedelta(hours=1)
        end = start + timedelta(hours=2)
        payload = {
            "handover_unit": "城东派出所",
            "goods_description": "涉案记录终端一批",
            "scheduled_start": start.isoformat(),
            "scheduled_end": end.isoformat(),
            "estimated_quantity": 20,
            "handlers": [
                {"name": "张三", "id_card": "110101199001011234", "phone": "13800000000"},
                {"name": "李四", "id_card": "", "phone": "13900000000"},
            ],
        }
        payload.update(overrides)
        return payload

    def create_appointment(self, client=None, **overrides):
        client = client or self.user_client
        response = client.post("/api/appointments/", self.appointment_payload(**overrides), format="json")
        assert response.status_code == 200, response.json()
        return response.json()["data"]

    def create_pending_for_checkin(self, start_offset=-1, end_offset=1):
        """创建时间窗覆盖当前时刻的预约（默认准时）"""
        return self.create_appointment(
            scheduled_start=(timezone.now() + timedelta(hours=start_offset)).isoformat(),
            scheduled_end=(timezone.now() + timedelta(hours=end_offset)).isoformat(),
        )

    def check_in_payload(self, **overrides):
        payload = {
            "handler_name": "张三",
            "handler_id_card": "110101199001011234",
            "actual_quantity": 20,
            "decision": "accepted",
            "goods": self.goods.id,
        }
        payload.update(overrides)
        return payload

    def check_in(self, appointment_id, **overrides):
        return self.admin_client.post(
            f"/api/appointments/{appointment_id}/check-in/",
            self.check_in_payload(**overrides),
            format="json"
        )


class AppointmentCreateTest(AppointmentFixture):
    def test_create_appointment(self):
        data = self.create_appointment()
        self.assertTrue(data["appointment_no"].startswith("AP"))
        self.assertEqual(data["status"], "pending")
        self.assertEqual(len(data["handlers"]), 2)

        appointment = Appointment.objects.get(pk=data["id"])
        self.assertEqual(appointment.created_by, self.unit_user)
        event = appointment.events.get(event_type="created")
        self.assertIn("城东派出所", event.detail)
        self.assertEqual(event.payload["estimated_quantity"], 20)

    def test_create_rejects_invalid_window(self):
        start = timezone.now() + timedelta(hours=2)
        response = self.user_client.post("/api/appointments/", self.appointment_payload(
            scheduled_start=start.isoformat(),
            scheduled_end=(start - timedelta(hours=1)).isoformat(),
        ), format="json")
        self.assertEqual(response.status_code, 400)

    def test_create_requires_handlers(self):
        response = self.user_client.post(
            "/api/appointments/", self.appointment_payload(handlers=[]), format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_create_rejects_duplicate_handler_names(self):
        response = self.user_client.post("/api/appointments/", self.appointment_payload(
            handlers=[{"name": "张三"}, {"name": "张三"}]
        ), format="json")
        self.assertEqual(response.status_code, 400)

    def test_estimated_quantity_must_be_positive(self):
        response = self.user_client.post(
            "/api/appointments/", self.appointment_payload(estimated_quantity=0), format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_authentication(self):
        anonymous = APIClient().get("/api/appointments/")
        self.assertEqual(anonymous.status_code, 401)


class AppointmentListTest(AppointmentFixture):
    def test_list_scoped_by_role(self):
        self.create_appointment(client=self.user_client)
        self.create_appointment(client=self.other_client)

        user_list = self.user_client.get("/api/appointments/").json()["data"]
        self.assertEqual(user_list["total"], 1)

        admin_list = self.admin_client.get("/api/appointments/").json()["data"]
        self.assertEqual(admin_list["total"], 2)

    def test_detail_forbidden_for_other_unit(self):
        data = self.create_appointment(client=self.user_client)
        response = self.other_client.get(f"/api/appointments/{data['id']}/")
        self.assertEqual(response.status_code, 403)

    def test_today_lists_covering_appointments(self):
        self.create_appointment(
            scheduled_start=(timezone.now() - timedelta(hours=1)).isoformat(),
            scheduled_end=(timezone.now() + timedelta(hours=1)).isoformat(),
        )
        self.create_appointment(
            scheduled_start=(timezone.now() + timedelta(days=2)).isoformat(),
            scheduled_end=(timezone.now() + timedelta(days=2, hours=2)).isoformat(),
        )
        response = self.admin_client.get("/api/appointments/today/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 1)


class AppointmentRescheduleTest(AppointmentFixture):
    def reschedule_payload(self, **overrides):
        new_start = timezone.now() + timedelta(days=1)
        payload = {
            "scheduled_start": new_start.isoformat(),
            "scheduled_end": (new_start + timedelta(hours=2)).isoformat(),
            "reason": "移交车辆调度冲突",
        }
        payload.update(overrides)
        return payload

    def test_reschedule_keeps_trail(self):
        data = self.create_appointment()
        response = self.user_client.post(
            f"/api/appointments/{data['id']}/reschedule/",
            self.reschedule_payload(),
            format="json"
        )
        self.assertEqual(response.status_code, 200)

        appointment = Appointment.objects.get(pk=data["id"])
        self.assertEqual(appointment.reschedule_count, 1)
        self.assertEqual(appointment.status, "pending")

        event = appointment.events.get(event_type="rescheduled")
        self.assertIn("移交车辆调度冲突", event.detail)
        self.assertIn("第1次", event.detail)
        self.assertEqual(event.payload["reschedule_count"], 1)
        self.assertIn("old", event.payload)
        self.assertIn("new", event.payload)

    def test_second_reschedule_increments_count(self):
        data = self.create_appointment()
        self.user_client.post(
            f"/api/appointments/{data['id']}/reschedule/", self.reschedule_payload(), format="json"
        )
        self.user_client.post(
            f"/api/appointments/{data['id']}/reschedule/",
            self.reschedule_payload(reason="再次调整"),
            format="json"
        )
        appointment = Appointment.objects.get(pk=data["id"])
        self.assertEqual(appointment.reschedule_count, 2)
        self.assertEqual(appointment.events.filter(event_type="rescheduled").count(), 2)

    def test_reschedule_forbidden_for_other_user(self):
        data = self.create_appointment()
        response = self.other_client.post(
            f"/api/appointments/{data['id']}/reschedule/",
            self.reschedule_payload(),
            format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_reschedule_requires_reason(self):
        data = self.create_appointment()
        payload = self.reschedule_payload()
        del payload["reason"]
        response = self.user_client.post(
            f"/api/appointments/{data['id']}/reschedule/", payload, format="json"
        )
        self.assertEqual(response.status_code, 400)


class AppointmentCancelTest(AppointmentFixture):
    def test_cancel_keeps_trail(self):
        data = self.create_appointment()
        response = self.user_client.post(
            f"/api/appointments/{data['id']}/cancel/",
            {"reason": "移交计划取消"},
            format="json"
        )
        self.assertEqual(response.status_code, 200)

        appointment = Appointment.objects.get(pk=data["id"])
        self.assertEqual(appointment.status, "cancelled")
        event = appointment.events.get(event_type="cancelled")
        self.assertIn("移交计划取消", event.detail)

    def test_cancel_requires_reason(self):
        data = self.create_appointment()
        response = self.user_client.post(
            f"/api/appointments/{data['id']}/cancel/", {}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_cancel_forbidden_for_other_user(self):
        data = self.create_appointment()
        response = self.other_client.post(
            f"/api/appointments/{data['id']}/cancel/",
            {"reason": "越权取消"},
            format="json"
        )
        self.assertEqual(response.status_code, 403)


class AppointmentCheckInTest(AppointmentFixture):
    def test_check_in_accept_creates_traceable_stock_in(self):
        data = self.create_pending_for_checkin()
        response = self.check_in(data["id"])
        self.assertEqual(response.status_code, 200)

        appointment = Appointment.objects.get(pk=data["id"])
        self.assertEqual(appointment.status, "received")

        check_in = appointment.check_in
        self.assertEqual(check_in.arrival_status, "on_time")
        self.assertTrue(check_in.identity_matched)
        self.assertEqual(check_in.received_quantity, 20)
        self.assertEqual(check_in.quantity_discrepancy, 0)

        # 正式入库记录可追溯预约
        stock_in = StockIn.objects.get(appointment=appointment)
        self.assertEqual(stock_in.quantity, Decimal("20"))
        self.assertEqual(stock_in.operator, self.admin)
        self.assertIn(appointment.appointment_no, stock_in.remark)

        # 库存增加
        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("32"))

        # 签到轨迹
        event = appointment.events.get(event_type="check_in")
        self.assertIn("接收", event.detail)
        self.assertEqual(event.payload["stock_in_id"], stock_in.id)

    def test_check_in_early_arrival_recorded(self):
        data = self.create_pending_for_checkin(start_offset=2, end_offset=4)
        response = self.check_in(data["id"])
        self.assertEqual(response.status_code, 200)

        appointment = Appointment.objects.get(pk=data["id"])
        self.assertEqual(appointment.check_in.arrival_status, "early")
        event = appointment.events.get(event_type="check_in")
        self.assertIn("提前", event.detail)

    def test_check_in_late_arrival_recorded(self):
        data = self.create_pending_for_checkin(start_offset=-4, end_offset=-2)
        response = self.check_in(data["id"])
        self.assertEqual(response.status_code, 200)

        appointment = Appointment.objects.get(pk=data["id"])
        self.assertEqual(appointment.check_in.arrival_status, "late")
        event = appointment.events.get(event_type="check_in")
        self.assertIn("迟到", event.detail)

    def test_duplicate_check_in_blocked_and_recorded(self):
        data = self.create_pending_for_checkin()
        first = self.check_in(data["id"])
        self.assertEqual(first.status_code, 200)

        second = self.check_in(data["id"])
        self.assertEqual(second.status_code, 400)

        appointment = Appointment.objects.get(pk=data["id"])
        self.assertEqual(appointment.events.filter(event_type="duplicate_check_in").count(), 1)
        # 仅一条有效签到与一条入库记录
        self.assertEqual(CheckIn.objects.filter(appointment=appointment).count(), 1)
        self.assertEqual(StockIn.objects.filter(appointment=appointment).count(), 1)

    def test_partial_receipt(self):
        data = self.create_pending_for_checkin()
        response = self.check_in(data["id"], decision="partial", received_quantity=15)
        self.assertEqual(response.status_code, 200)

        appointment = Appointment.objects.get(pk=data["id"])
        self.assertEqual(appointment.status, "partial_received")

        stock_in = StockIn.objects.get(appointment=appointment)
        self.assertEqual(stock_in.quantity, Decimal("15"))

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("27"))

    def test_partial_requires_received_less_than_actual(self):
        data = self.create_pending_for_checkin()
        response = self.check_in(data["id"], decision="partial", received_quantity=20)
        self.assertEqual(response.status_code, 400)

    def test_accepted_received_must_equal_actual(self):
        data = self.create_pending_for_checkin()
        response = self.check_in(data["id"], decision="accepted", received_quantity=18)
        self.assertEqual(response.status_code, 400)

    def test_reject_requires_reason(self):
        data = self.create_pending_for_checkin()
        response = self.check_in(data["id"], decision="rejected", remark="")
        self.assertEqual(response.status_code, 400)

    def test_reject_creates_no_stock_in(self):
        data = self.create_pending_for_checkin()
        response = self.check_in(data["id"], decision="rejected", remark="包装破损，拒绝接收")
        self.assertEqual(response.status_code, 200)

        appointment = Appointment.objects.get(pk=data["id"])
        self.assertEqual(appointment.status, "rejected")
        self.assertFalse(StockIn.objects.filter(appointment=appointment).exists())

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("12"))

    def test_identity_mismatch_recorded(self):
        data = self.create_pending_for_checkin()
        response = self.check_in(data["id"], handler_name="王五", handler_id_card="")
        self.assertEqual(response.status_code, 200)

        appointment = Appointment.objects.get(pk=data["id"])
        self.assertFalse(appointment.check_in.identity_matched)
        event = appointment.events.get(event_type="check_in")
        self.assertIn("不一致", event.detail)

    def test_identity_mismatch_on_wrong_id_card(self):
        data = self.create_pending_for_checkin()
        response = self.check_in(data["id"], handler_id_card="999999999999999999")
        self.assertEqual(response.status_code, 200)

        appointment = Appointment.objects.get(pk=data["id"])
        self.assertFalse(appointment.check_in.identity_matched)

    def test_check_in_requires_duty_officer(self):
        data = self.create_pending_for_checkin()
        response = self.user_client.post(
            f"/api/appointments/{data['id']}/check-in/",
            self.check_in_payload(),
            format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_check_in_cancelled_appointment_rejected(self):
        data = self.create_appointment()
        self.user_client.post(
            f"/api/appointments/{data['id']}/cancel/",
            {"reason": "计划变更"},
            format="json"
        )
        response = self.check_in(data["id"])
        self.assertEqual(response.status_code, 400)

    def test_check_in_requires_goods_for_receipt(self):
        data = self.create_pending_for_checkin()
        payload = self.check_in_payload()
        del payload["goods"]
        response = self.admin_client.post(
            f"/api/appointments/{data['id']}/check-in/", payload, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_reschedule_after_check_in_rejected(self):
        data = self.create_pending_for_checkin()
        self.check_in(data["id"])

        new_start = timezone.now() + timedelta(days=1)
        response = self.user_client.post(
            f"/api/appointments/{data['id']}/reschedule/",
            {
                "scheduled_start": new_start.isoformat(),
                "scheduled_end": (new_start + timedelta(hours=2)).isoformat(),
                "reason": "尝试改期",
            },
            format="json"
        )
        self.assertEqual(response.status_code, 400)


class StockInTraceTest(AppointmentFixture):
    def test_stock_in_list_exposes_appointment(self):
        data = self.create_pending_for_checkin()
        self.check_in(data["id"])

        response = self.admin_client.get(f"/api/stock-in/?appointment_id={data['id']}")
        self.assertEqual(response.status_code, 200)

        payload = response.json()["data"]
        self.assertEqual(payload["total"], 1)
        record = payload["list"][0]
        self.assertEqual(record["appointment"], data["id"])
        self.assertEqual(record["appointment_no"], data["appointment_no"])

    def test_appointment_detail_contains_full_trail(self):
        data = self.create_pending_for_checkin()
        self.check_in(data["id"], actual_quantity=18, decision="partial", received_quantity=15)

        response = self.admin_client.get(f"/api/appointments/{data['id']}/")
        self.assertEqual(response.status_code, 200)

        detail = response.json()["data"]
        # 签到记录与现场差异
        self.assertEqual(detail["check_in"]["actual_quantity"], 18)
        self.assertEqual(detail["check_in"]["quantity_discrepancy"], -2)
        # 入库记录
        self.assertEqual(len(detail["stock_ins"]), 1)
        self.assertEqual(detail["stock_ins"][0]["quantity"], "15.00")
        # 轨迹：创建 + 签到
        event_types = [event["event_type"] for event in detail["events"]]
        self.assertEqual(event_types, ["created", "check_in"])
