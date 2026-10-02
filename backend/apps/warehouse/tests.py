from decimal import Decimal
from datetime import datetime, timedelta

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from .models import (
    Approval, Appointment, AppointmentEvent, Category, Goods, Reception,
    StockIn, StockOut, Unit, Variety, Warning,
)


class WarehouseFixture(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("warehouse-user", "testpass123", role="admin")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.user)}")
        self.unit = Unit.objects.create(name="件", created_by=self.user)
        self.category = Category.objects.create(name="受控器材", unit=self.unit, created_by=self.user)
        self.variety = Variety.objects.create(name="记录终端", category=self.category, created_by=self.user)
        self.goods = Goods.objects.create(
            variety=self.variety,
            name="执法记录终端",
            code="DEV-001",
            quantity=Decimal("12"),
            warning_threshold=Decimal("5"),
        )


class WarehouseModelTest(WarehouseFixture):
    def test_relationship_flags(self):
        self.assertTrue(self.unit.is_linked)
        self.assertTrue(self.category.is_linked)
        self.assertTrue(self.variety.is_in_stock)
        self.assertFalse(self.goods.is_warning)

    def test_unique_unit_name(self):
        with self.assertRaises(IntegrityError):
            Unit.objects.create(name="件", created_by=self.user)

    def test_stock_records_and_approval(self):
        inbound = StockIn.objects.create(goods=self.goods, operator=self.user, quantity=Decimal("3"))
        outbound = StockOut.objects.create(
            goods=self.goods, operator=self.user, receiver="保管员", quantity=Decimal("2")
        )
        approval = Approval.objects.create(stock_out=outbound, approver=self.user)
        self.assertEqual(inbound.goods_id, self.goods.id)
        self.assertEqual(approval.status, "pending")

    def test_warning_record(self):
        warning = Warning.objects.create(goods=self.goods, type="low_stock", message="库存不足")
        self.assertFalse(warning.is_read)
        self.assertIn("执法记录终端", str(warning))


class WarehouseAPITest(WarehouseFixture):
    def test_list_units(self):
        response = self.client.get("/api/units/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["total"], 1)

    def test_create_unit_and_reject_duplicate(self):
        created = self.client.post("/api/units/", {"name": "箱"}, format="json")
        duplicate = self.client.post("/api/units/", {"name": "箱"}, format="json")
        self.assertEqual(created.status_code, 200)
        self.assertEqual(duplicate.status_code, 400)

    def test_update_linked_unit(self):
        response = self.client.put(f"/api/units/{self.unit.id}/", {"name": "台"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.name, "台")

    def test_refuse_delete_linked_unit(self):
        response = self.client.delete(f"/api/units/{self.unit.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Unit.objects.filter(pk=self.unit.id).exists())

    def test_create_category_validates_unit(self):
        ok = self.client.post("/api/categories/", {"name": "封存介质", "unit": self.unit.id}, format="json")
        bad = self.client.post("/api/categories/", {"name": "无效分类", "unit": 99999}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(bad.status_code, 400)

    def test_create_variety_and_duplicate_boundary(self):
        ok = self.client.post("/api/varieties/", {"name": "封存硬盘", "category": self.category.id}, format="json")
        duplicate = self.client.post("/api/varieties/", {"name": "封存硬盘", "category": self.category.id}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(duplicate.status_code, 400)

    def test_requires_authentication(self):
        anonymous = APIClient().get("/api/units/")
        self.assertEqual(anonymous.status_code, 401)


class AppointmentFixture(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("appointment-user", "testpass123", role="admin")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.user)}")
        self.unit = Unit.objects.create(name="件", created_by=self.user)
        self.category = Category.objects.create(name="受控器材", unit=self.unit, created_by=self.user)
        self.variety = Variety.objects.create(name="记录终端", category=self.category, created_by=self.user)
        self.goods = Goods.objects.create(
            variety=self.variety,
            name="执法记录终端",
            code="DEV-001",
            quantity=Decimal("12"),
            warning_threshold=Decimal("5"),
        )

    def create_appointment(self, start_offset=timedelta(hours=-1), end_offset=timedelta(hours=1), **overrides):
        defaults = dict(
            appointment_no=Appointment.generate_appointment_no(),
            transfer_unit="第一稽查队",
            expected_start=timezone.now() + start_offset,
            expected_end=timezone.now() + end_offset,
            expected_quantity=50,
            handover_person="张三",
            handover_person_phone="13800000000",
            handover_person_id_card="110101199001011234",
            created_by=self.user,
        )
        defaults.update(overrides)
        return Appointment.objects.create(**defaults)

    def appointment_payload(self, **overrides):
        now = timezone.now()
        payload = {
            "transfer_unit": "第一稽查队",
            "expected_start": (now + timedelta(hours=1)).isoformat(),
            "expected_end": (now + timedelta(hours=3)).isoformat(),
            "expected_quantity": 50,
            "handover_person": "张三",
            "handover_person_phone": "13800000000",
            "handover_person_id_card": "110101199001011234",
        }
        payload.update(overrides)
        return payload

    def check_in_payload(self, **overrides):
        payload = {
            "actual_person": "张三",
            "actual_person_id_card": "110101199001011234",
            "identity_verified": True,
            "actual_quantity": 50,
            "decision": "receive",
        }
        payload.update(overrides)
        return payload

    def check_in(self, appointment, **overrides):
        return self.client.post(
            f"/api/appointments/{appointment.id}/check-in/",
            self.check_in_payload(**overrides),
            format="json",
        )


class AppointmentModelTest(AppointmentFixture):
    def test_appointment_no_sequence(self):
        first = self.create_appointment()
        second = self.create_appointment()
        self.assertTrue(first.appointment_no.startswith("AP"))
        self.assertEqual(int(second.appointment_no[-4:]), int(first.appointment_no[-4:]) + 1)

    def test_arrival_status_boundaries(self):
        appointment = self.create_appointment()
        self.assertEqual(
            appointment.arrival_status_at(appointment.expected_start - timedelta(seconds=1)),
            "early",
        )
        self.assertEqual(appointment.arrival_status_at(appointment.expected_start), "on_time")
        self.assertEqual(appointment.arrival_status_at(appointment.expected_end), "on_time")
        self.assertEqual(
            appointment.arrival_status_at(appointment.expected_end + timedelta(seconds=1)),
            "late",
        )

    def test_quantity_difference(self):
        appointment = self.create_appointment(expected_quantity=50)
        reception = Reception.objects.create(
            appointment=appointment,
            duty_officer=self.user,
            arrival_status="on_time",
            actual_person="张三",
            identity_verified=True,
            actual_quantity=48,
            decision="partial",
            received_quantity=45,
        )
        self.assertEqual(reception.quantity_difference, -2)


class AppointmentAPITest(AppointmentFixture):
    def test_create_appointment_records_created_event(self):
        response = self.client.post("/api/appointments/", self.appointment_payload(), format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "pending")
        self.assertTrue(data["appointment_no"].startswith("AP"))
        self.assertEqual(data["events"][0]["event_type"], "created")
        self.assertEqual(data["events"][0]["detail"]["expected_quantity"], 50)
        self.assertEqual(data["events"][0]["detail"]["handover_person"], "张三")

    def test_create_appointment_validates_window_and_quantity(self):
        now = timezone.now()
        bad_window = self.appointment_payload(
            expected_start=(now + timedelta(hours=2)).isoformat(),
            expected_end=(now + timedelta(hours=1)).isoformat(),
        )
        response = self.client.post("/api/appointments/", bad_window, format="json")
        self.assertEqual(response.status_code, 400)

        bad_quantity = self.appointment_payload(expected_quantity=0)
        response = self.client.post("/api/appointments/", bad_quantity, format="json")
        self.assertEqual(response.status_code, 400)

    def test_list_appointments_filters(self):
        self.create_appointment(transfer_unit="第一稽查队")
        self.create_appointment(transfer_unit="第二稽查队", status="cancelled")

        response = self.client.get("/api/appointments/", {"status": "pending"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["total"], 1)

        response = self.client.get("/api/appointments/", {"transfer_unit": "第二"})
        data = response.json()["data"]
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["list"][0]["transfer_unit"], "第二稽查队")

    def test_reschedule_keeps_trail(self):
        appointment = self.create_appointment()
        old_start = appointment.expected_start
        new_start = timezone.now() + timedelta(days=1)
        new_end = new_start + timedelta(hours=2)
        response = self.client.post(
            f"/api/appointments/{appointment.id}/reschedule/",
            {
                "expected_start": new_start.isoformat(),
                "expected_end": new_end.isoformat(),
                "reason": "车辆故障",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.expected_start, new_start)
        event = appointment.events.get(event_type="rescheduled")
        self.assertEqual(datetime.fromisoformat(event.detail["old_start"]), old_start)
        self.assertEqual(datetime.fromisoformat(event.detail["new_start"]), new_start)
        self.assertEqual(event.detail["reason"], "车辆故障")

    def test_reschedule_rejected_after_check_in(self):
        appointment = self.create_appointment()
        response = self.check_in(appointment)
        self.assertEqual(response.status_code, 200)

        new_start = timezone.now() + timedelta(days=1)
        response = self.client.post(
            f"/api/appointments/{appointment.id}/reschedule/",
            {
                "expected_start": new_start.isoformat(),
                "expected_end": (new_start + timedelta(hours=2)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_cancel_appointment_blocks_check_in(self):
        appointment = self.create_appointment()
        response = self.client.post(
            f"/api/appointments/{appointment.id}/cancel/",
            {"reason": "计划变更"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "cancelled")
        self.assertTrue(appointment.events.filter(event_type="cancelled").exists())

        response = self.check_in(appointment)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            AppointmentEvent.objects.filter(
                appointment=appointment, event_type="duplicate_check_in"
            ).exists()
        )

    def test_check_in_receive_creates_traceable_stock_in(self):
        appointment = self.create_appointment()
        response = self.check_in(
            appointment,
            stock_ins=[{"goods": self.goods.id, "quantity": "50", "batch_no": "B20261002"}],
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "received")
        self.assertEqual(data["reception"]["arrival_status"], "on_time")
        self.assertEqual(data["reception"]["received_quantity"], 50)
        self.assertTrue(data["reception"]["identity_verified"])

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("62"))

        stock_in = StockIn.objects.get(appointment=appointment)
        self.assertEqual(stock_in.supplier, "第一稽查队")
        self.assertEqual(stock_in.operator, self.user)
        self.assertEqual(stock_in.batch_no, "B20261002")

        event_types = list(appointment.events.values_list("event_type", flat=True))
        self.assertEqual(event_types, ["check_in", "received"])
        received_event = appointment.events.get(event_type="received")
        self.assertEqual(received_event.detail["stock_in_ids"], [stock_in.id])

    def test_check_in_early_and_late_arrival(self):
        early = self.create_appointment(
            start_offset=timedelta(hours=2), end_offset=timedelta(hours=4)
        )
        response = self.check_in(early)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["reception"]["arrival_status"], "early")

        late = self.create_appointment(
            start_offset=timedelta(hours=-4), end_offset=timedelta(hours=-2)
        )
        response = self.check_in(late)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["reception"]["arrival_status"], "late")

    def test_check_in_partial_receive(self):
        appointment = self.create_appointment(expected_quantity=50)
        response = self.check_in(
            appointment,
            actual_quantity=48,
            decision="partial",
            received_quantity=45,
            discrepancy_note="3件包装破损拒收",
            stock_ins=[{"goods": self.goods.id, "quantity": "45"}],
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "partial")
        self.assertEqual(data["reception"]["received_quantity"], 45)
        self.assertEqual(data["reception"]["quantity_difference"], -2)
        self.assertEqual(data["reception"]["discrepancy_note"], "3件包装破损拒收")

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("57"))
        self.assertTrue(appointment.events.filter(event_type="partial_received").exists())

    def test_check_in_partial_requires_note_and_valid_quantity(self):
        appointment = self.create_appointment()
        response = self.check_in(
            appointment, actual_quantity=48, decision="partial", received_quantity=45
        )
        self.assertEqual(response.status_code, 400)

        response = self.check_in(
            appointment,
            actual_quantity=48,
            decision="partial",
            received_quantity=48,
            discrepancy_note="数量差异",
        )
        self.assertEqual(response.status_code, 400)

    def test_check_in_reject(self):
        appointment = self.create_appointment()
        response = self.check_in(
            appointment, decision="reject", discrepancy_note="证件与预约不符"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "rejected")
        self.assertEqual(data["reception"]["received_quantity"], 0)

        self.goods.refresh_from_db()
        self.assertEqual(self.goods.quantity, Decimal("12"))
        self.assertFalse(StockIn.objects.filter(appointment=appointment).exists())
        self.assertTrue(appointment.events.filter(event_type="rejected").exists())

    def test_check_in_unverified_identity_must_reject(self):
        appointment = self.create_appointment()
        response = self.check_in(appointment, identity_verified=False, decision="receive")
        self.assertEqual(response.status_code, 400)

        response = self.check_in(
            appointment,
            identity_verified=False,
            decision="reject",
            discrepancy_note="身份核验未通过",
        )
        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "rejected")

    def test_duplicate_check_in_keeps_trail(self):
        appointment = self.create_appointment()
        first = self.check_in(appointment)
        self.assertEqual(first.status_code, 200)

        second = self.check_in(appointment)
        self.assertEqual(second.status_code, 400)

        event = appointment.events.get(event_type="duplicate_check_in")
        self.assertEqual(event.actor, self.user)
        self.assertIn("original_check_in_time", event.detail)
        self.assertEqual(Reception.objects.filter(appointment=appointment).count(), 1)

    def test_appointment_detail_contains_full_trail(self):
        appointment = self.create_appointment()
        new_start = timezone.now() + timedelta(days=1)
        self.client.post(
            f"/api/appointments/{appointment.id}/reschedule/",
            {
                "expected_start": new_start.isoformat(),
                "expected_end": (new_start + timedelta(hours=2)).isoformat(),
            },
            format="json",
        )
        self.check_in(
            appointment,
            actual_quantity=48,
            decision="partial",
            received_quantity=45,
            discrepancy_note="3件包装破损拒收",
            stock_ins=[{"goods": self.goods.id, "quantity": "45"}],
        )

        response = self.client.get(f"/api/appointments/{appointment.id}/")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        event_types = [event["event_type"] for event in data["events"]]
        self.assertEqual(event_types, ["rescheduled", "check_in", "partial_received"])
        self.assertEqual(data["reception"]["decision"], "partial")
        self.assertEqual(len(data["stock_ins"]), 1)
        self.assertEqual(data["stock_ins"][0]["appointment_no"], appointment.appointment_no)

    def test_stock_in_list_traces_appointment(self):
        appointment = self.create_appointment()
        self.check_in(
            appointment,
            stock_ins=[{"goods": self.goods.id, "quantity": "50"}],
        )
        StockIn.objects.create(goods=self.goods, operator=self.user, quantity=Decimal("1"))

        response = self.client.get("/api/stock-in/", {"appointment": appointment.id})
        data = response.json()["data"]
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["list"][0]["appointment_no"], appointment.appointment_no)

        response = self.client.get("/api/stock-in/")
        rows = response.json()["data"]["list"]
        self.assertEqual(len(rows), 2)
        manual = [row for row in rows if row["appointment"] is None][0]
        self.assertIsNone(manual["appointment_no"])

    def test_requires_authentication(self):
        anonymous = APIClient().get("/api/appointments/")
        self.assertEqual(anonymous.status_code, 401)
