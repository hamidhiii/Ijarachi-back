# Rentoo Postman

Import these two files into Postman:

1. `Rentoo.postman_environment.json`
2. `Rentoo.postman_collection.json`

Use the `Rentoo Local` environment. Start with `Auth / SMS Send`, then put the OTP from the backend log into `otp`, then run `Auth / SMS Verify`. The verify request saves `access_token` and `refresh_token` automatically.

For local dev with empty Eskiz credentials, the backend logs the OTP instead of sending SMS.

MyID callback is a dev-friendly simulation: call `MyID Callback` with `state` from `MyID Start` and any `code`. Production MyID token exchange still needs real partner credentials.
