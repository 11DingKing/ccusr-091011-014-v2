"""
仓库管理序列化器
"""
from decimal import Decimal
from rest_framework import serializers
from .models import (
    Unit, Category, Variety, Goods, StockIn, StockOut, Warning, Approval,
    Appointment, Reception, AppointmentEvent
)


class UnitSerializer(serializers.ModelSerializer):
    """单位序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    
    class Meta:
        model = Unit
        fields = [
            'id', 'name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class UnitCreateSerializer(serializers.Serializer):
    """单位创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=5, required=True, error_messages={
        'required': '请输入单位名称',
        'blank': '单位名称不能为空',
        'min_length': '单位名称至少1个字',
        'max_length': '单位名称最多5个字',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Unit.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('单位名称已存在')
        else:
            if Unit.objects.filter(name=value).exists():
                raise serializers.ValidationError('单位名称已存在')
        return value


class CategorySerializer(serializers.ModelSerializer):
    """品类序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    unit_name = serializers.CharField(source='unit.name', read_only=True)
    
    class Meta:
        model = Category
        fields = [
            'id', 'name', 'unit', 'unit_name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CategoryCreateSerializer(serializers.Serializer):
    """品类创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=10, required=True, error_messages={
        'required': '请输入品类名称',
        'blank': '品类名称不能为空',
        'min_length': '品类名称至少1个字',
        'max_length': '品类名称最多10个字',
    })
    unit = serializers.IntegerField(required=True, error_messages={
        'required': '请选择单位',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Category.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('品类名称已存在')
        else:
            if Category.objects.filter(name=value).exists():
                raise serializers.ValidationError('品类名称已存在')
        return value
    
    def validate_unit(self, value):
        if not Unit.objects.filter(pk=value).exists():
            raise serializers.ValidationError('单位不存在')
        return value


class VarietySerializer(serializers.ModelSerializer):
    """品种序列化器"""
    is_in_stock = serializers.BooleanField(read_only=True)
    unit_name = serializers.CharField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    
    class Meta:
        model = Variety
        fields = [
            'id', 'name', 'category', 'category_name', 'unit_name',
            'is_in_stock', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class VarietyCreateSerializer(serializers.Serializer):
    """品种创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=20, required=True, error_messages={
        'required': '请输入品种名称',
        'blank': '品种名称不能为空',
        'min_length': '品种名称至少1个字',
        'max_length': '品种名称最多20个字',
    })
    category = serializers.IntegerField(required=True, error_messages={
        'required': '请选择品类',
    })
    
    def validate_category(self, value):
        if not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError('品类不存在')
        return value
    
    def validate(self, data):
        instance = self.context.get('instance')
        name = data['name']
        category_id = data['category']
        
        if instance:
            if Variety.objects.filter(name=name, category_id=category_id).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        else:
            if Variety.objects.filter(name=name, category_id=category_id).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        return data


class GoodsSerializer(serializers.ModelSerializer):
    """货物序列化器"""
    variety_name = serializers.CharField(source='variety.name', read_only=True)
    category_name = serializers.CharField(source='variety.category.name', read_only=True)
    unit_name = serializers.CharField(source='variety.category.unit.name', read_only=True)
    is_warning = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Goods
        fields = [
            'id', 'name', 'code', 'variety', 'variety_name',
            'category_name', 'unit_name', 'specification',
            'quantity', 'warning_threshold', 'location',
            'remark', 'is_active', 'is_warning',
            'created_at', 'updated_at'
        ]


class StockInSerializer(serializers.ModelSerializer):
    """入库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    appointment_no = serializers.SerializerMethodField()

    class Meta:
        model = StockIn
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'quantity', 'batch_no', 'supplier', 'appointment', 'appointment_no',
            'stock_in_time', 'remark'
        ]

    def get_appointment_no(self, obj):
        return obj.appointment.appointment_no if obj.appointment else None


class StockOutSerializer(serializers.ModelSerializer):
    """出库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = StockOut
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'receiver', 'receiver_dept', 'quantity', 'status', 'status_display',
            'stock_out_time', 'remark', 'created_at'
        ]


class WarningSerializer(serializers.ModelSerializer):
    """预警记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    
    class Meta:
        model = Warning
        fields = [
            'id', 'goods', 'goods_name', 'type', 'type_display',
            'message', 'is_read', 'created_at'
        ]


class ApprovalSerializer(serializers.ModelSerializer):
    """审批记录序列化器"""
    approver_name = serializers.CharField(source='approver.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Approval
        fields = [
            'id', 'stock_out', 'approver', 'approver_name',
            'status', 'status_display', 'remark', 'created_at', 'updated_at'
        ]


# ==================== 到场预约 ====================

class AppointmentEventSerializer(serializers.ModelSerializer):
    """预约轨迹序列化器"""
    actor_name = serializers.CharField(source='actor.username', read_only=True)
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)

    class Meta:
        model = AppointmentEvent
        fields = [
            'id', 'event_type', 'event_type_display',
            'actor', 'actor_name', 'detail', 'created_at'
        ]


class ReceptionSerializer(serializers.ModelSerializer):
    """签到接收记录序列化器"""
    duty_officer_name = serializers.CharField(source='duty_officer.username', read_only=True)
    arrival_status_display = serializers.CharField(source='get_arrival_status_display', read_only=True)
    decision_display = serializers.CharField(source='get_decision_display', read_only=True)
    quantity_difference = serializers.IntegerField(read_only=True)

    class Meta:
        model = Reception
        fields = [
            'id', 'duty_officer', 'duty_officer_name', 'check_in_time',
            'arrival_status', 'arrival_status_display',
            'actual_person', 'actual_person_id_card', 'identity_verified',
            'actual_quantity', 'decision', 'decision_display',
            'received_quantity', 'quantity_difference',
            'discrepancy_note', 'created_at'
        ]


class AppointmentSerializer(serializers.ModelSerializer):
    """预约详情序列化器（含签到记录、轨迹与入库记录）"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    reception = ReceptionSerializer(read_only=True)
    events = AppointmentEventSerializer(many=True, read_only=True)
    stock_ins = StockInSerializer(many=True, read_only=True)

    class Meta:
        model = Appointment
        fields = [
            'id', 'appointment_no', 'transfer_unit',
            'expected_start', 'expected_end', 'expected_quantity',
            'handover_person', 'handover_person_phone', 'handover_person_id_card',
            'status', 'status_display', 'remark',
            'created_by', 'created_by_name', 'created_at', 'updated_at',
            'reception', 'events', 'stock_ins'
        ]


class AppointmentListSerializer(serializers.ModelSerializer):
    """预约列表序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    arrival_status = serializers.CharField(source='reception.arrival_status', read_only=True)
    arrival_status_display = serializers.CharField(
        source='reception.get_arrival_status_display', read_only=True
    )
    decision = serializers.CharField(source='reception.decision', read_only=True)

    class Meta:
        model = Appointment
        fields = [
            'id', 'appointment_no', 'transfer_unit',
            'expected_start', 'expected_end', 'expected_quantity',
            'handover_person', 'handover_person_phone',
            'status', 'status_display',
            'arrival_status', 'arrival_status_display', 'decision',
            'created_by', 'created_by_name', 'created_at'
        ]


class AppointmentCreateSerializer(serializers.Serializer):
    """预约创建序列化器"""
    transfer_unit = serializers.CharField(min_length=1, max_length=100, required=True, error_messages={
        'required': '请输入移交单位',
        'blank': '移交单位不能为空',
        'max_length': '移交单位最多100个字',
    })
    expected_start = serializers.DateTimeField(required=True, error_messages={
        'required': '请选择预约开始时间',
    })
    expected_end = serializers.DateTimeField(required=True, error_messages={
        'required': '请选择预约结束时间',
    })
    expected_quantity = serializers.IntegerField(min_value=1, required=True, error_messages={
        'required': '请输入预估件数',
        'min_value': '预估件数至少为1',
    })
    handover_person = serializers.CharField(min_length=1, max_length=50, required=True, error_messages={
        'required': '请输入交接人员',
        'blank': '交接人员不能为空',
        'max_length': '交接人员最多50个字',
    })
    handover_person_phone = serializers.CharField(min_length=1, max_length=20, required=True, error_messages={
        'required': '请输入联系电话',
        'blank': '联系电话不能为空',
        'max_length': '联系电话最多20个字',
    })
    handover_person_id_card = serializers.CharField(max_length=18, required=False, allow_blank=True, default='')
    remark = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        if data['expected_end'] <= data['expected_start']:
            raise serializers.ValidationError('预约结束时间必须晚于开始时间')
        return data


class AppointmentRescheduleSerializer(serializers.Serializer):
    """预约改期序列化器"""
    expected_start = serializers.DateTimeField(required=True, error_messages={
        'required': '请选择预约开始时间',
    })
    expected_end = serializers.DateTimeField(required=True, error_messages={
        'required': '请选择预约结束时间',
    })
    reason = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        if data['expected_end'] <= data['expected_start']:
            raise serializers.ValidationError('预约结束时间必须晚于开始时间')
        return data


class StockInItemSerializer(serializers.Serializer):
    """签到入库明细序列化器"""
    goods = serializers.IntegerField(required=True, error_messages={
        'required': '请选择货物',
    })
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        min_value=Decimal('0.01'), required=True,
        error_messages={
            'required': '请输入入库数量',
            'min_value': '入库数量必须大于0',
        }
    )
    batch_no = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    remark = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_goods(self, value):
        if not Goods.objects.filter(pk=value, is_active=True).exists():
            raise serializers.ValidationError('货物不存在或已停用')
        return value


class CheckInSerializer(serializers.Serializer):
    """签到接收序列化器"""
    actual_person = serializers.CharField(min_length=1, max_length=50, required=True, error_messages={
        'required': '请输入实际交接人',
        'blank': '实际交接人不能为空',
        'max_length': '实际交接人最多50个字',
    })
    actual_person_id_card = serializers.CharField(max_length=18, required=False, allow_blank=True, default='')
    identity_verified = serializers.BooleanField(required=True, error_messages={
        'required': '请确认身份核验结果',
    })
    actual_quantity = serializers.IntegerField(min_value=0, required=True, error_messages={
        'required': '请输入实际件数',
        'min_value': '实际件数不能为负数',
    })
    decision = serializers.ChoiceField(
        choices=['receive', 'partial', 'reject'], required=True,
        error_messages={
            'required': '请选择接收决定',
            'invalid_choice': '无效的接收决定',
        }
    )
    received_quantity = serializers.IntegerField(min_value=0, required=False)
    discrepancy_note = serializers.CharField(required=False, allow_blank=True, default='')
    stock_ins = StockInItemSerializer(many=True, required=False, default=list)

    def validate(self, data):
        decision = data['decision']
        actual_quantity = data['actual_quantity']
        received_quantity = data.get('received_quantity')

        if not data['identity_verified'] and decision != 'reject':
            raise serializers.ValidationError('身份核验未通过，只能拒收')

        if decision == 'receive':
            if actual_quantity < 1:
                raise serializers.ValidationError('实际件数必须大于0才能接收')
            data['received_quantity'] = actual_quantity
        elif decision == 'partial':
            if received_quantity is None:
                raise serializers.ValidationError('部分接收时必须填写实收件数')
            if not 0 < received_quantity < actual_quantity:
                raise serializers.ValidationError('实收件数必须大于0且小于实际件数')
        else:
            if received_quantity:
                raise serializers.ValidationError('拒收时实收件数必须为0')
            data['received_quantity'] = 0
            if data.get('stock_ins'):
                raise serializers.ValidationError('拒收时不能创建入库记录')

        if decision != 'receive' and not data.get('discrepancy_note'):
            raise serializers.ValidationError('部分接收或拒收时必须填写差异说明')

        return data
