# Rentoo Postman

Import these two files into Postman:

1. `Rentoo.postman_environment.json`
2. `Rentoo.postman_collection.json`

Use the `Rentoo Local` environment. Start with `Auth / SMS Send`, then put the OTP from the backend log into `otp`, then run `Auth / SMS Verify`. The verify request saves `access_token` and `refresh_token` automatically.

For local dev with empty Eskiz credentials, the backend logs the OTP instead of sending SMS.

MyID callback is a dev-friendly simulation: call `MyID Callback` with `state` from `MyID Start` and any `code`. Production MyID token exchange still needs real partner credentials.

Mobile-facing additions are included in the collection:

- `GET /api/v1/users/:id/`
- `GET /api/v1/users/:id/listings/`
- `GET /api/v1/listings/?owner=:id`
- `DELETE /api/v1/listings/:id/`
- `GET/PATCH /api/v1/listings/:id/availability/`
- `GET/POST /api/v1/favorites/`, `DELETE /api/v1/favorites/:listing_id/`
- `GET /api/v1/listings/:id/reviews/`, `POST /api/v1/deals/:id/review/`
- `POST /api/v1/deals/:id/photos/`
- `POST /api/v1/chat/conversations/:id/read/`
- `POST /api/v1/notifications/read-all/`

Chat creation uses `deal_id` only and is available after successful payment.
