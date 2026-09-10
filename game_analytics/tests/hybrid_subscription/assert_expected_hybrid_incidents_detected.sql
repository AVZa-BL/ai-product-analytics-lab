with expected as (
    select *
    from (values
        ('duplicate_store_webhook'),
        ('mixed_timestamp_mismatch'),
        ('missing_subscription_grant_link'),
        ('post_subscription_exposure'),
        ('cancellation_pending_expiry')
    ) as required(incident_code)
)
select expected.incident_code
from expected
left join {{ ref('mart_hybrid_subscription__data_quality_incidents') }} incident
    using (incident_code)
where incident.incident_code is null
    or incident.affected_rows <= 0
    or incident.decision_status != 'contained'
