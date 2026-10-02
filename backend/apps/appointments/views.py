"""
到场预约视图
"""
import logging
from datetime import datetime
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from apps.core.response import success_response, error_response
from apps.warehouse.models import Goods, StockIn
from apps.warehouse.serializers import StockInSerializer
from .models import Appointment, AppointmentHandler, CheckIn, generate_appointment_no
from .serializers import (
    AppointmentCreateSerializer, AppointmentListSerializer, AppointmentDetailSerializer,
    CheckInSerializer, CheckInCreateSerializer, RescheduleSerializer, CancelSerializer
)

logger = logging.getLogger('apps')


def _first_error(errors):
    """提取序列化器错误中的首个错误信息"""
    if isinstance(errors, dict):
        for value in errors.values():
            message = _first_error(value)
            if message:
                return message
    elif isinstance(errors, (list, tuple)):
        for item in errors:
            message = _first_error(item)
            if message:
                return message
    elif errors:
        return str(errors)
    return ''


def _fmt(dt):
    """格式化时间用于轨迹描述"""
    return timezone.localtime(dt).strftime('%Y-%m-%d %H:%M')


def _can_manage(user, appointment):
    """是否可管理该预约（值班员/管理员或预约创建人）"""
    return user.is_admin or appointment.created_by_id == user.id


def _check_in_detail(appointment, check_in):
    """生成签到轨迹描述"""
    arrival_display = dict(CheckIn.ARRIVAL_STATUS_CHOICES)[check_in.arrival_status]
    head = f"值班员{check_in.duty_officer.username}签到：{arrival_display}"
    if check_in.arrival_status == 'late':
        minutes = int((check_in.arrival_time - appointment.scheduled_end).total_seconds() // 60)
        head += f"，迟到{minutes}分钟"
    elif check_in.arrival_status == 'early':
        minutes = int((appointment.scheduled_start - check_in.arrival_time).total_seconds() // 60)
        head += f"，提前{minutes}分钟"

    parts = [
        head,
        f"实到{check_in.actual_quantity}件（预估{appointment.estimated_quantity}件）"
    ]
    decision_display = dict(CheckIn.DECISION_CHOICES)[check_in.decision]
    if check_in.decision == 'rejected':
        parts.append(f"决定{decision_display}")
    else:
        parts.append(f"决定{decision_display}，接收{check_in.received_quantity}件")
    if not check_in.identity_matched:
        parts.append("交接人身份与预约声明不一致")
    return '；'.join(parts)


class AppointmentListView(APIView):
    """预约列表视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Appointment.objects.all()
        # 移交单位用户只能查看本单位创建的预约，值班员/管理员可查看全部
        if not request.user.is_admin:
            queryset = queryset.filter(created_by=request.user)

        status_param = request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param)

        date_param = request.query_params.get('date')
        if date_param:
            try:
                target_date = datetime.strptime(date_param, '%Y-%m-%d').date()
            except ValueError:
                return error_response(message='日期格式应为YYYY-MM-DD')
            queryset = queryset.filter(
                scheduled_start__date__lte=target_date,
                scheduled_end__date__gte=target_date
            )

        keyword = request.query_params.get('keyword')
        if keyword:
            queryset = queryset.filter(
                Q(appointment_no__icontains=keyword) |
                Q(handover_unit__icontains=keyword)
            )

        queryset = queryset.order_by('scheduled_start', 'id')

        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        start = (page - 1) * page_size
        end = start + page_size

        total = queryset.count()
        appointments = queryset[start:end]

        serializer = AppointmentListSerializer(appointments, many=True)

        return success_response(data={
            'list': serializer.data,
            'total': total,
            'page': page,
            'page_size': page_size
        })

    def post(self, request):
        """创建到场预约"""
        serializer = AppointmentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors) or '参数校验失败')

        data = serializer.validated_data
        appointment = None
        # 预约编号按当日序号生成，冲突时重试
        for _ in range(3):
            try:
                with transaction.atomic():
                    appointment = Appointment.objects.create(
                        appointment_no=generate_appointment_no(),
                        handover_unit=data['handover_unit'],
                        goods_description=data['goods_description'],
                        scheduled_start=data['scheduled_start'],
                        scheduled_end=data['scheduled_end'],
                        estimated_quantity=data['estimated_quantity'],
                        remark=data.get('remark', ''),
                        created_by=request.user
                    )
                    for handler in data['handlers']:
                        AppointmentHandler.objects.create(appointment=appointment, **handler)
                    appointment.record_event(
                        'created', request.user,
                        detail=(
                            f"创建预约：{appointment.handover_unit} 预约 "
                            f"{_fmt(appointment.scheduled_start)}~{_fmt(appointment.scheduled_end)}，"
                            f"预估{appointment.estimated_quantity}件"
                        ),
                        payload={
                            'handover_unit': appointment.handover_unit,
                            'scheduled_start': appointment.scheduled_start.isoformat(),
                            'scheduled_end': appointment.scheduled_end.isoformat(),
                            'estimated_quantity': appointment.estimated_quantity,
                            'handlers': data['handlers']
                        }
                    )
                break
            except IntegrityError:
                appointment = None

        if appointment is None:
            return error_response(message='预约编号生成失败，请重试')

        logger.info(f"User {request.user.username} created appointment {appointment.appointment_no}")

        return success_response(
            data=AppointmentDetailSerializer(appointment).data,
            message='预约创建成功'
        )


class AppointmentTodayView(APIView):
    """当日到场预约视图（值班员签到台）"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        queryset = Appointment.objects.filter(
            scheduled_start__date__lte=today,
            scheduled_end__date__gte=today
        ).order_by('scheduled_start', 'id')
        if not request.user.is_admin:
            queryset = queryset.filter(created_by=request.user)

        serializer = AppointmentListSerializer(queryset, many=True)
        return success_response(data=serializer.data)


class AppointmentDetailView(APIView):
    """预约详情视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        appointment = Appointment.objects.filter(pk=pk).first()
        if not appointment:
            return error_response(message='预约不存在', code=404)

        if not _can_manage(request.user, appointment):
            return error_response(message='无权限查看该预约', code=403)

        return success_response(data=AppointmentDetailSerializer(appointment).data)


class AppointmentRescheduleView(APIView):
    """预约改期视图"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        appointment = Appointment.objects.filter(pk=pk).first()
        if not appointment:
            return error_response(message='预约不存在', code=404)

        if not _can_manage(request.user, appointment):
            return error_response(message='无权限修改该预约', code=403)

        if not appointment.is_pending:
            return error_response(message='当前状态不允许改期')

        serializer = RescheduleSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors) or '参数校验失败')

        data = serializer.validated_data
        old_start, old_end = appointment.scheduled_start, appointment.scheduled_end

        appointment.scheduled_start = data['scheduled_start']
        appointment.scheduled_end = data['scheduled_end']
        appointment.reschedule_count += 1
        appointment.save(update_fields=[
            'scheduled_start', 'scheduled_end', 'reschedule_count', 'updated_at'
        ])

        appointment.record_event(
            'rescheduled', request.user,
            detail=(
                f"预约改期（第{appointment.reschedule_count}次）："
                f"{_fmt(old_start)}~{_fmt(old_end)} 改为 "
                f"{_fmt(appointment.scheduled_start)}~{_fmt(appointment.scheduled_end)}，"
                f"原因：{data['reason']}"
            ),
            payload={
                'old': {
                    'scheduled_start': old_start.isoformat(),
                    'scheduled_end': old_end.isoformat()
                },
                'new': {
                    'scheduled_start': appointment.scheduled_start.isoformat(),
                    'scheduled_end': appointment.scheduled_end.isoformat()
                },
                'reason': data['reason'],
                'reschedule_count': appointment.reschedule_count
            }
        )

        logger.info(f"User {request.user.username} rescheduled appointment {appointment.appointment_no}")

        return success_response(
            data=AppointmentDetailSerializer(appointment).data,
            message='改期成功'
        )


class AppointmentCancelView(APIView):
    """预约取消视图"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        appointment = Appointment.objects.filter(pk=pk).first()
        if not appointment:
            return error_response(message='预约不存在', code=404)

        if not _can_manage(request.user, appointment):
            return error_response(message='无权限取消该预约', code=403)

        if not appointment.is_pending:
            return error_response(message='当前状态不允许取消')

        serializer = CancelSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors) or '参数校验失败')

        reason = serializer.validated_data['reason']
        appointment.status = 'cancelled'
        appointment.save(update_fields=['status', 'updated_at'])

        appointment.record_event(
            'cancelled', request.user,
            detail=f"取消预约，原因：{reason}",
            payload={'reason': reason}
        )

        logger.info(f"User {request.user.username} cancelled appointment {appointment.appointment_no}")

        return success_response(
            data=AppointmentDetailSerializer(appointment).data,
            message='预约已取消'
        )


class AppointmentCheckInView(APIView):
    """值班员签到视图：核对身份与实际数量并决定接收结果"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not request.user.is_admin:
            return error_response(message='仅值班员可执行签到接收', code=403)

        appointment = Appointment.objects.filter(pk=pk).first()
        if not appointment:
            return error_response(message='预约不存在', code=404)

        if appointment.status == 'cancelled':
            return error_response(message='预约已取消，无法签到')

        if not appointment.is_pending:
            # 重复签到：保留轨迹并拒绝
            appointment.record_event(
                'duplicate_check_in', request.user,
                detail=f"值班员{request.user.username}重复签到被拦截",
                payload={
                    'handler_name': request.data.get('handler_name', ''),
                    'attempted_at': timezone.now().isoformat()
                }
            )
            logger.warning(
                f"Duplicate check-in blocked: appointment {appointment.appointment_no} "
                f"by {request.user.username}"
            )
            return error_response(message='该预约已完成签到，请勿重复签到')

        serializer = CheckInCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors) or '参数校验失败')

        data = serializer.validated_data
        now = timezone.now()
        arrival_status = appointment.compute_arrival_status(now)
        matched_handler = appointment.match_handler(
            data['handler_name'], data.get('handler_id_card', '')
        )
        identity_matched = matched_handler is not None
        decision = data['decision']
        received_quantity = data['received_quantity']

        with transaction.atomic():
            check_in = CheckIn.objects.create(
                appointment=appointment,
                duty_officer=request.user,
                handler_name=data['handler_name'],
                handler_id_card=data.get('handler_id_card', ''),
                identity_matched=identity_matched,
                actual_quantity=data['actual_quantity'],
                decision=decision,
                received_quantity=received_quantity,
                goods_id=data.get('goods') if decision in ('accepted', 'partial') else None,
                arrival_time=now,
                arrival_status=arrival_status,
                remark=data.get('remark', '')
            )

            status_map = {
                'accepted': 'received',
                'partial': 'partial_received',
                'rejected': 'rejected'
            }
            appointment.status = status_map[decision]
            appointment.save(update_fields=['status', 'updated_at'])

            stock_in = None
            if decision in ('accepted', 'partial'):
                goods = Goods.objects.select_for_update().get(pk=data['goods'])
                stock_in = StockIn.objects.create(
                    goods=goods,
                    operator=request.user,
                    quantity=received_quantity,
                    appointment=appointment,
                    remark=(
                        f"关联预约{appointment.appointment_no}；"
                        f"预估{appointment.estimated_quantity}件，"
                        f"实到{check_in.actual_quantity}件，"
                        f"接收{received_quantity}件"
                    )
                )
                goods.quantity = F('quantity') + received_quantity
                goods.save(update_fields=['quantity', 'updated_at'])

            appointment.record_event(
                'check_in', request.user,
                detail=_check_in_detail(appointment, check_in),
                payload={
                    'arrival_status': arrival_status,
                    'arrival_time': now.isoformat(),
                    'handler_name': check_in.handler_name,
                    'handler_id_card': check_in.handler_id_card,
                    'identity_matched': identity_matched,
                    'estimated_quantity': appointment.estimated_quantity,
                    'actual_quantity': check_in.actual_quantity,
                    'decision': decision,
                    'received_quantity': received_quantity,
                    'stock_in_id': stock_in.id if stock_in else None
                }
            )

        logger.info(
            f"User {request.user.username} checked in appointment {appointment.appointment_no}: "
            f"{arrival_status}, decision={decision}"
        )

        message_map = {
            'accepted': '签到完成，物资已接收',
            'partial': '签到完成，物资部分接收',
            'rejected': '签到完成，物资已拒收'
        }
        return success_response(data={
            'check_in': CheckInSerializer(check_in).data,
            'stock_in': StockInSerializer(stock_in).data if stock_in else None
        }, message=message_map[decision])
