"""
到场预约模型
"""
from django.db import models
from django.utils import timezone
from apps.authentication.models import User


def generate_appointment_no():
    """生成预约编号：AP + 日期 + 当日序号"""
    today = timezone.localdate()
    prefix = f"AP{today:%Y%m%d}"
    seq = Appointment.objects.filter(appointment_no__startswith=prefix).count() + 1
    return f"{prefix}{seq:04d}"


class Appointment(models.Model):
    """到场预约模型"""

    STATUS_CHOICES = [
        ('pending', '待签到'),
        ('received', '已接收'),
        ('partial_received', '部分接收'),
        ('rejected', '已拒收'),
        ('cancelled', '已取消'),
    ]

    appointment_no = models.CharField('预约编号', max_length=20, unique=True)
    handover_unit = models.CharField('移交单位', max_length=100)
    goods_description = models.CharField('物资说明', max_length=200)
    scheduled_start = models.DateTimeField('预约时间窗开始')
    scheduled_end = models.DateTimeField('预约时间窗结束')
    estimated_quantity = models.PositiveIntegerField('预估件数')
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    reschedule_count = models.PositiveIntegerField('改期次数', default=0)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='appointments', verbose_name='创建人'
    )
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'ap_appointment'
        verbose_name = '到场预约'
        verbose_name_plural = verbose_name
        ordering = ['scheduled_start', 'id']

    def __str__(self):
        return f"{self.appointment_no} - {self.handover_unit}"

    @property
    def is_pending(self):
        """是否待签到"""
        return self.status == 'pending'

    def match_handler(self, name, id_card=''):
        """核对到场人员是否为预约声明的交接人员"""
        name = (name or '').strip()
        id_card = (id_card or '').strip()
        for handler in self.handlers.all():
            if handler.name != name:
                continue
            declared_id_card = (handler.id_card or '').strip()
            # 预约未登记证件号或现场未提供证件号时，按姓名核对；均提供时须一致
            if not declared_id_card or not id_card or declared_id_card == id_card:
                return handler
        return None

    def compute_arrival_status(self, arrival_time):
        """根据预约时间窗计算到场状态"""
        if arrival_time < self.scheduled_start:
            return 'early'
        if arrival_time > self.scheduled_end:
            return 'late'
        return 'on_time'

    def record_event(self, event_type, operator, detail='', payload=None):
        """记录预约轨迹"""
        return AppointmentEvent.objects.create(
            appointment=self,
            event_type=event_type,
            operator=operator,
            detail=detail,
            payload=payload or {}
        )


class AppointmentHandler(models.Model):
    """预约交接人员模型"""
    appointment = models.ForeignKey(
        Appointment, on_delete=models.CASCADE,
        related_name='handlers', verbose_name='到场预约'
    )
    name = models.CharField('姓名', max_length=50)
    id_card = models.CharField('证件号', max_length=18, blank=True)
    phone = models.CharField('手机号', max_length=20, blank=True)

    class Meta:
        db_table = 'ap_appointment_handler'
        verbose_name = '预约交接人员'
        verbose_name_plural = verbose_name
        ordering = ['id']

    def __str__(self):
        return f"{self.appointment.appointment_no} - {self.name}"


class CheckIn(models.Model):
    """到场签到记录模型（每个预约仅一条有效签到）"""

    DECISION_CHOICES = [
        ('accepted', '接收'),
        ('partial', '部分接收'),
        ('rejected', '拒收'),
    ]

    ARRIVAL_STATUS_CHOICES = [
        ('on_time', '准时'),
        ('early', '提前到场'),
        ('late', '迟到'),
    ]

    appointment = models.OneToOneField(
        Appointment, on_delete=models.CASCADE,
        related_name='check_in', verbose_name='到场预约'
    )
    duty_officer = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='appointment_check_ins', verbose_name='值班员'
    )
    handler_name = models.CharField('实际交接人姓名', max_length=50)
    handler_id_card = models.CharField('实际交接人证件号', max_length=18, blank=True)
    identity_matched = models.BooleanField('身份核对通过', default=False)
    actual_quantity = models.PositiveIntegerField('实际件数')
    decision = models.CharField('接收决定', max_length=20, choices=DECISION_CHOICES)
    received_quantity = models.PositiveIntegerField('接收件数', default=0)
    goods = models.ForeignKey(
        'warehouse.Goods', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='appointment_check_ins', verbose_name='入库货物'
    )
    arrival_time = models.DateTimeField('签到时间', default=timezone.now)
    arrival_status = models.CharField('到场状态', max_length=20, choices=ARRIVAL_STATUS_CHOICES)
    remark = models.TextField('现场备注', blank=True)
    created_at = models.DateTimeField('记录时间', auto_now_add=True)

    class Meta:
        db_table = 'ap_check_in'
        verbose_name = '到场签到记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.appointment.appointment_no} - {self.get_decision_display()}"

    @property
    def quantity_discrepancy(self):
        """现场差异（实际件数 - 预估件数）"""
        return self.actual_quantity - self.appointment.estimated_quantity


class AppointmentEvent(models.Model):
    """预约轨迹模型"""

    EVENT_CHOICES = [
        ('created', '创建预约'),
        ('rescheduled', '预约改期'),
        ('check_in', '签到接收'),
        ('duplicate_check_in', '重复签到'),
        ('cancelled', '取消预约'),
    ]

    appointment = models.ForeignKey(
        Appointment, on_delete=models.CASCADE,
        related_name='events', verbose_name='到场预约'
    )
    event_type = models.CharField('事件类型', max_length=20, choices=EVENT_CHOICES)
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='appointment_events', verbose_name='操作人'
    )
    detail = models.TextField('轨迹描述', blank=True)
    payload = models.JSONField('事件快照', default=dict, blank=True)
    created_at = models.DateTimeField('发生时间', auto_now_add=True)

    class Meta:
        db_table = 'ap_appointment_event'
        verbose_name = '预约轨迹'
        verbose_name_plural = verbose_name
        ordering = ['created_at', 'id']

    def __str__(self):
        return f"{self.appointment.appointment_no} - {self.get_event_type_display()}"
