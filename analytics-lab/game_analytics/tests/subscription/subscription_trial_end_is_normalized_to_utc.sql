select *
from {{ ref('stg_subscription__subscription_events') }}
where event_type = 'trial_started'
  and trial_timezone <> 'UTC'
  and trial_end_at_utc = cast(raw_trial_end_at_reported_utc as timestamp)
