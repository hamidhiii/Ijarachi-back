# Rentoo Postman

Import these two files into Postman:

1. `Rentoo.postman_environment.json`
2. `Rentoo.postman_collection.json`

Use the `Rentoo Local` environment. Start with `Auth / SMS Send`, then put the OTP from the backend log into `otp`, then run `Auth / SMS Verify`. The verify request saves `access_token` and `refresh_token` automatically.

For local dev with empty Eskiz credentials, the backend logs the OTP instead of sending SMS.

KYC is a self-hosted two-step pipeline (no third-party MyID dependency):

1. `KYC (passport + face) / 1. Passport Upload` — upload a photo of the ID card/passport (`front_image`, optional `back_image`). The backend OCRs the document and extracts a face embedding, returns the recognized fields.
2. `KYC (passport + face) / 2. Passport Confirm` — client reviews/corrects the OCR'd fields (`series`, `number`, `pinfl`, `full_name`, `birth_date`, ...) and confirms them; the document is marked verified.
3. `KYC (passport + face) / 3. Face Verify` — upload 1-3 selfie frames (`frame_1..3`, from camera or file). The backend matches the face against the document and checks liveness across frames; on success the profile is marked KYC-verified automatically.

`GET` variants of the passport/face endpoints return the current status of each step. `GET /api/v1/users/me/verification/` returns the overall profile verification status.

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
