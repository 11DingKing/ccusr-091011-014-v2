"""
到场预约序列化器
"""
from rest_framework import serializers
from apps.warehouse.models import Goods
from apps.warehouse.serializers import StockInSerializer
from .models import Appointment, AppointmentHandler, CheckIn, AppointmentEvent


class AppointmentHandlerSerializer(serializers.ModelSerializer):
    """预约交接人员序列化器"""

    class Meta:
        model = AppointmentHandler
        fields = ['id', 'name', 'id_card', 'phone']


class HandlerInputSerializer(serializers.Serializer):
    """交接人员登记序列化器"""
    name = serializers.CharField(max_length=50, required=True, error_messages={
        'required': '请填写交接人员姓名',
        'blank': '交接人员姓名不能为空',
    })
    id_card = serializers.CharField(max_length=18, required=False, allow_blank=True, default='')
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')


class AppointmentCreateSerializer(serializers.Serializer):
    """预约创建序列化器"""
    handover_unit = serializers.CharField(max_length=100, required=True, error_messages={
        'required': '请填写移交单位',
        'blank': '移交单位不能为空',
    })
    goods_description = serializers.CharField(max_length=200, required=True, error_messages={
        'required': '请填写物资说明',
        'blank': '物资说明不能为空',
    })
    scheduled_start = serializers.DateTimeField(required=True, error_messages={
        'required': '请选择预约时间窗开始时间',
        'invalid': '预约时间窗开始时间格式不正确',
    })
    scheduled_end = serializers.DateTimeField(required=True, error_messages={
        'required': '请选择预约时间窗结束时间',
        'invalid': '预约时间窗结束时间格式不正确',
    })
    estimated_quantity = serializers.IntegerField(min_value=1, required=True, error_messages={
        'required': '请填写预估件数',
        'min_value': '预估件数至少为1',
    })
    handlers = HandlerInputSerializer(many=True, required=True, error_messages={
        'required': '请登记交接人员',
    })
    remark = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_handlers(self, value):
        if not value:
            raise serializers.ValidationError('请至少登记一名交接人员')
        names = [item['name'].strip() for item in value]
        if len(names) != len(set(names)):
            raise serializers.ValidationError('交接人员姓名不能重复')
        return value

    def validate(self, data):
        if data['scheduled_end'] <= data['scheduled_start']:
            raise serializers.ValidationError('预约时间窗结束时间必须晚于开始时间')
        return data


class RescheduleSerializer(serializers.Serializer):
    """预约改期序列化器"""
    scheduled_start = serializers.DateTimeField(required=True, error_messages={
        'required': '请选择新的时间窗开始时间',
        'invalid': '时间窗开始时间格式不正确',
    })
    scheduled_end = serializers.DateTimeField(required=True, error_messages={
        'required': '请选择新的时间窗结束时间',
        'invalid': '时间窗结束时间格式不正确',
    })
    reason = serializers.CharField(max_length=200, required=True, error_messages={
        'required': '请填写改期原因',
        'blank': '改期原因不能为空',
    })

    def validate(self, data):
        if data['scheduled_end'] <= data['scheduled_start']:
            raise serializers.ValidationError('预约时间窗结束时间必须晚于开始时间')
        return data


class CancelSerializer(serializers.Serializer):
    """预约取消序列化器"""
    reason = serializers.CharField(max_length=200, required=True, error_messages={
        'required': '请填写取消原因',
        'blank': '取消原因不能为空',
    })


class CheckInCreateSerializer(serializers.Serializer):
    """签到接收序列化器"""
    handler_name = serializers.CharField(max_length=50, required=True, error_messages={
        'required': '请填写实际交接人姓名',
        'blank': '实际交接人姓名不能为空',
    })
    handler_id_card = serializers.CharField(max_length=18, required=False, allow_blank=True, default='')
    actual_quantity = serializers.IntegerField(min_value=0, required=True, error_messages={
        'required': '请填写实际件数',
        'min_value': '实际件数不能为负数',
    })
    decision = serializers.ChoiceField(choices=CheckIn.DECISION_CHOICES, required=True, error_messages={
        'required': '请选择接收决定',
        'invalid_choice': '无效的接收决定',
    })
    received_quantity = serializers.IntegerField(min_value=0, required=False, error_messages={
        'min_value': '接收件数不能为负数',
    })
    goods = serializers.IntegerField(required=False)
    remark = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_goods(self, value):
        if value is not None and not Goods.objects.filter(pk=value, is_active=True).exists():
            raise serializers.ValidationError('货物不存在或已停用')
        return value

    def validate(self, data):
        decision = data['decision']
        actual = data['actual_quantity']
        received = data.get('received_quantity')

        if decision == 'accepted':
            if received is not None and received != actual:
                raise serializers.ValidationError('接收决定为接收时，接收件数须等于实际件数')
            data['received_quantity'] = actual
        elif decision == 'partial':
            if received is None:
                raise serializers.ValidationError('部分接收时必须填写接收件数')
            if not 0 < received < actual:
                raise serializers.ValidationError('部分接收时接收件数必须大于0且小于实际件数')
        elif decision == 'rejected':
            if received:
                raise serializers.ValidationError('拒收时接收件数必须为0')
            data['received_quantity'] = 0
            if not data.get('remark'):
                raise serializers.ValidationError('拒收时必须填写拒收原因')

        if decision in ('accepted', 'partial'):
            if data['received_quantity'] <= 0:
                raise serializers.ValidationError('接收件数必须大于0')
            if not data.get('goods'):
                raise serializers.ValidationError('接收入库时必须选择货物')
        return data


class AppointmentListSerializer(serializers.ModelSerializer):
    """预约列表序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    handler_count = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            'id', 'appointment_no', 'handover_unit', 'goods_description',
            'scheduled_start', 'scheduled_end', 'estimated_quantity',
            'status', 'status_display', 'reschedule_count', 'handler_count',
            'created_by', 'created_by_name', 'remark', 'created_at'
        ]

    def get_handler_count(self, obj):
        return obj.handlers.count()


class CheckInSerializer(serializers.ModelSerializer):
    """签到记录序列化器"""
    duty_officer_name = serializers.CharField(source='duty_officer.username', read_only=True)
    decision_display = serializers.CharField(source='get_decision_display', read_only=True)
    arrival_status_display = serializers.CharField(source='get_arrival_status_display', read_only=True)
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    quantity_discrepancy = serializers.IntegerField(read_only=True)

    class Meta:
        model = CheckIn
        fields = [
            'id', 'appointment', 'duty_officer', 'duty_officer_name',
            'handler_name', 'handler_id_card', 'identity_matched',
            'actual_quantity', 'decision', 'decision_display',
            'received_quantity', 'goods', 'goods_name',
            'arrival_time', 'arrival_status', 'arrival_status_display',
            'quantity_discrepancy', 'remark', 'created_at'
        ]


class AppointmentEventSerializer(serializers.ModelSerializer):
    """预约轨迹序列化器"""
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)

    class Meta:
        model = AppointmentEvent
        fields = [
            'id', 'event_type', 'event_type_display', 'operator', 'operator_name',
            'detail', 'payload', 'created_at'
        ]


class AppointmentDetailSerializer(serializers.ModelSerializer):
    """预约详情序列化器（含交接人员、签到记录、轨迹与入库记录）"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    handlers = AppointmentHandlerSerializer(many=True, read_only=True)
    check_in = CheckInSerializer(read_only=True)
    events = AppointmentEventSerializer(many=True, read_only=True)
    stock_ins = StockInSerializer(many=True, read_only=True)

    class Meta:
        model = Appointment
        fields = [
            'id', 'appointment_no', 'handover_unit', 'goods_description',
            'scheduled_start', 'scheduled_end', 'estimated_quantity',
            'status', 'status_display', 'reschedule_count',
            'created_by', 'created_by_name', 'remark',
            'handlers', 'check_in', 'events', 'stock_ins',
            'created_at', 'updated_at'
        ]
