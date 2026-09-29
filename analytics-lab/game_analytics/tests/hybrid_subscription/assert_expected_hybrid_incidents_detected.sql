with expected as (
    select *
    from (values
        ('duplicate_store_webhook', true),
        ('mixed_timestamp_mismatch', false),
        ('missing_subscription_grant_link', true),
        ('post_subscription_exposure', true),
        ('cancellation_pending_expiry', true)
    ) as required(incident_code, requires_affected_rows)
)
select expected.incident_code
from expected
left join {{ ref('mart_hybrid_subscription__data_quality_incidents') }} incident
    using (incident_code)
where incident.incident_code is null
    or (expected.requires_affected_rows and incident.affected_rows <= 0)
    or (incident.affected_rows > 0 and incident.decision_status != 'contained')
    or (incident.affected_rows = 0 and incident.decision_status != 'clear')
