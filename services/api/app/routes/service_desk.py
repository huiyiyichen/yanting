from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_context, get_session, require_support
from app.domain.consumer_service import (
    incidents,
    operators,
    risk_judgments,
    service_breakpoints,
    tickets,
)
from app.domain.consumer_service.workspace import reception_snapshot
from app.routes.commit import CommitBeforeResponseRoute
from app.schemas.service_breakpoints import ServiceBreakpointAssessmentView
from app.schemas.service_desk import (
    DemoOperatorRosterView,
    ReceptionStatsView,
    RiskIncidentDetailView,
    RiskIncidentStatusRequest,
    RiskIncidentView,
    RiskInterventionRequest,
    RiskJudgmentExportView,
    RiskJudgmentRequest,
    RiskScanView,
    TicketCreateRequest,
    TicketUpdateRequest,
    TicketView,
)

router = APIRouter(
    prefix="/api/support/desk", tags=["service-desk"],
    route_class=CommitBeforeResponseRoute, dependencies=[Depends(require_support)],
)


@router.get("/operators", response_model=DemoOperatorRosterView)
def operator_roster():
    return operators.roster()


@router.get("/stats", response_model=ReceptionStatsView)
def stats(session: Session = Depends(get_session)):
    snapshot = reception_snapshot(session)
    risk = incidents.list_incidents(session)
    return ReceptionStatsView(
        live_conversations=sum(item.data_source == "live" for item in snapshot.items),
        historical_conversations=sum(item.data_source != "live" for item in snapshot.items),
        unread_messages=snapshot.unread_total,
        open_tickets=sum(item.status != "resolved" for item in tickets.list_tickets(session)),
        pending_risks=sum(item.current_action in {"intervene", "review"} for item in risk),
    )


@router.get("/tickets", response_model=list[TicketView])
def ticket_list(conversation_id: str | None = None, session: Session = Depends(get_session)):
    return tickets.list_tickets(session, conversation_id)


@router.get("/tickets/{ticket_id}", response_model=TicketView)
def ticket_detail(ticket_id: str, session: Session = Depends(get_session)):
    return tickets.get_ticket(session, ticket_id)


@router.post("/tickets", response_model=TicketView)
def ticket_create(
    payload: TicketCreateRequest, session: Session = Depends(get_session),
    actor: str = Depends(operators.current_operator),
):
    return tickets.create_ticket(session, payload, actor=actor)


@router.put("/tickets/{ticket_id}", response_model=TicketView)
def ticket_update(
    ticket_id: str, payload: TicketUpdateRequest, session: Session = Depends(get_session),
    actor: str = Depends(operators.current_operator),
):
    return tickets.update_ticket(session, ticket_id, payload, actor=actor)


@router.get("/risks", response_model=list[RiskIncidentView])
def risk_list(session: Session = Depends(get_session)):
    return incidents.list_incidents(session)


@router.get("/conversations/{conversation_id}/risks", response_model=list[RiskIncidentView])
def conversation_risks(conversation_id: str, session: Session = Depends(get_session)):
    return incidents.list_incidents(session, conversation_id=conversation_id)


@router.post("/risks/scan", response_model=RiskScanView)
def risk_scan(session: Session = Depends(get_session)):
    return incidents.scan_risks(session)


@router.get("/risk-judgments/export", response_model=RiskJudgmentExportView)
def risk_judgment_export(session: Session = Depends(get_session)):
    return risk_judgments.export_judgments(session)


@router.post("/risks/{incident_id}/signals/{alert_id}/judgment", response_model=RiskIncidentDetailView)
def risk_judgment(
    incident_id: str, alert_id: str, payload: RiskJudgmentRequest,
    session: Session = Depends(get_session), actor: str = Depends(operators.current_operator),
):
    return risk_judgments.record_judgment(session, incident_id, alert_id, payload, actor=actor)


@router.get("/breakpoints/{conversation_id}", response_model=ServiceBreakpointAssessmentView)
def breakpoint_assessment(conversation_id: str, session: Session = Depends(get_session)):
    from app.repositories.consumer_service import ConsumerServiceRepository

    ConsumerServiceRepository(session).context(conversation_id)
    return service_breakpoints.read_assessment(session, conversation_id)


@router.post("/breakpoints/{conversation_id}", response_model=ServiceBreakpointAssessmentView)
def breakpoint_analyze(
    conversation_id: str, session: Session = Depends(get_session), runtime=Depends(get_context),
    actor: str = Depends(operators.current_operator),
):
    from app.audit.recorder import AuditContext, AuditRecorder
    from app.domain.consumer_service.grounding import record_failure
    from app.errors import AnkerAgentError

    try:
        service_breakpoints.analyze_service_breakpoints(
            session, runtime.model_provider, runtime, conversation_id,
        )
        AuditRecorder(session).record(
            AuditContext.new_turn(actor_type="operator", conversation_id=conversation_id),
            event_type="service_breakpoint_analysis_requested", detail={"operator": actor},
        )
        return service_breakpoints.read_assessment(session, conversation_id)
    except AnkerAgentError as exc:
        session.rollback()
        record_failure(session, conversation_id, exc)
        session.commit()
        raise


@router.get("/risks/{incident_id}", response_model=RiskIncidentDetailView)
def risk_detail(incident_id: str, session: Session = Depends(get_session)):
    return incidents.incident_detail(session, incident_id)


@router.post("/risks/{incident_id}/status", response_model=RiskIncidentDetailView)
def risk_update(
    incident_id: str, payload: RiskIncidentStatusRequest, session: Session = Depends(get_session),
    actor: str = Depends(operators.current_operator),
):
    return incidents.update_incident(
        session, incident_id, payload.status, payload.note, payload.expected_version,
        actor=actor,
    )


@router.post("/risks/{incident_id}/intervene", response_model=RiskIncidentDetailView)
def risk_intervene(
    incident_id: str, payload: RiskInterventionRequest, session: Session = Depends(get_session),
    actor: str = Depends(operators.current_operator),
):
    return incidents.intervene(
        session, incident_id, payload.conversation_id, payload.expected_version, actor=actor,
    )
