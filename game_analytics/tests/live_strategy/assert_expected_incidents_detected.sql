with expected(incident_code) as (
    values
        ('duplicate_android_client_events'),
        ('missing_android_session_ends'),
        ('purchase_refund_status_lag'),
        ('events_before_install'),
        ('invalid_membership_interval'),
        ('ambiguous_intraday_configuration_join')
)

select incident_code
from expected

except

select distinct incident_code
from {{ ref('mart_live_strategy__data_quality_incidents') }}
where affected_record_count > 0
