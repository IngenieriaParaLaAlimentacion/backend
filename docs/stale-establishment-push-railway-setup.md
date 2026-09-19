# Stale-establishment push notifications: Firebase and Railway setup

This guide configures the backend to send Firebase Cloud Messaging (FCM) notifications.
The persistent FastAPI server owns the hourly scheduler; no Railway cron service or HTTP
callback is required. Complete the test environment first, then repeat the process with
separate production credentials.

## Before you begin

You need:

- access to the Firebase and Google Cloud projects;
- access to the Railway project and its backend service;
- the backend deployment containing migration `f4b8c2d91e06`;
- the Android application IDs:
  - test: `ar.com.ingenieriaalimentacion.tst`;
  - production: `ar.com.ingenieriaalimentacion`.

Use separate Firebase projects for test and production. Never copy a production service
account key into a test environment, a local `.env` committed to Git, or the mobile app.

## 1. Prepare each Firebase project

Repeat these steps once for test and once for production.

1. Open the Firebase console and select the correct project.
2. Open **Project settings → Cloud Messaging**.
3. Confirm that the **Firebase Cloud Messaging API (V1)** is enabled. If it is disabled,
   enable it in the linked Google Cloud project.
4. Record the Firebase project ID shown in **Project settings → General**.
5. Confirm that the corresponding Android app exists:
   - test Firebase project: `ar.com.ingenieriaalimentacion.tst`;
   - production Firebase project: `ar.com.ingenieriaalimentacion`.
6. Download that Android app's `google-services.json`.
7. Check that `project_info.project_id` in the downloaded file matches the Firebase
   project ID recorded above.

Do not commit either Android configuration file. Provision them out of band at these
paths when building the mobile application:

```text
composeApp/src/tst/google-services.json
composeApp/src/prod/google-services.json
```

## 2. Create a backend FCM service account

Prefer a dedicated service account instead of a broadly privileged project account.

1. Open the linked Google Cloud project.
2. Go to **IAM & Admin → Service Accounts**.
3. Create a service account such as `backend-fcm-sender`.
4. Grant it **Firebase Cloud Messaging API Admin**
   (`roles/firebasecloudmessaging.admin`).
5. Open the service account, select **Keys → Add key → Create new key**, and choose JSON.
6. Download the JSON key once and store it securely.

The downloaded JSON contains the three backend values used below:

| Railway variable | JSON field |
| --- | --- |
| `FCM_PROJECT_ID` | `project_id` |
| `FCM_CLIENT_EMAIL` | `client_email` |
| `FCM_PRIVATE_KEY` | `private_key` |

The project ID must match the Android `google-services.json` for the same environment.
The private key is a server credential and must never be included in the mobile app.

## 3. Choose the activation instant

The activation instant prevents old outflows from generating an immediate historical
notification burst. Choose it immediately before the first scheduled run for that
environment.

Use an offset-aware UTC value:

```text
STALE_NOTIFICATIONS_FEATURE_ACTIVATED_AT=YYYY-MM-DDTHH:MM:SSZ
```

Example format only:

```text
STALE_NOTIFICATIONS_FEATURE_ACTIVATED_AT=2026-09-19T18:00:00Z
```

Do not reuse the example blindly. Record the real rollout time in UTC.

## 4. Configure the Railway backend service

1. Open the Railway project.
2. Select the correct environment: test or production.
3. Select the backend service.
4. Open **Variables**.
5. Add these four variables:

```text
FCM_PROJECT_ID=<project_id from the service-account JSON>
FCM_CLIENT_EMAIL=<client_email from the service-account JSON>
FCM_PRIVATE_KEY=<complete private_key from the service-account JSON>
STALE_NOTIFICATIONS_FEATURE_ACTIVATED_AT=<real UTC rollout instant>
```

For `FCM_PRIVATE_KEY`, paste the entire PEM value, including its header and footer:

```text
-----BEGIN PRIVATE KEY-----
...
-----END PRIVATE KEY-----
```

Railway accepts multiline variables. A single-line value containing literal `\n`
characters also works because the backend normalizes it before creating the Google
credential.

6. Seal `FCM_PRIVATE_KEY` from its three-dot menu.
7. Review and deploy the staged Railway changes.

`FCM_PROJECT_ID`, `FCM_CLIENT_EMAIL`, and the activation instant are configuration rather
than secrets, but they should still remain server-side.

## 5. Verify the backend deployment

The Docker startup command applies Alembic migrations automatically. After deployment:

1. Confirm the deployment completed successfully.
2. Confirm migration `f4b8c2d91e06` was applied.
3. Confirm the backend health endpoint is healthy.
4. Confirm the logs contain `Stale-establishment scheduler started` with timezone
   `America/Argentina/Buenos_Aires` and active hours `8-22`.
5. After an active-hour boundary, confirm the logs contain a completed run or a lock-skip
   entry when another server process owns the run.

The scheduler logs a configuration error instead of stopping FastAPI when activation or
FCM credentials are incomplete. A due threshold is not advanced when there are no eligible
registered devices.

## 6. Provision and verify the mobile environment

Before deploying the configured production backend:

1. Put the matching environment's `google-services.json` in its ignored flavor path.
2. Configure `api_url_tst` locally for test builds when required.
3. Build and install the correct flavor.
4. Sign in as an active field worker with an approved establishment relation.
5. Confirm the backend contains a device registration for that installation.
6. Verify token rotation re-registers the same installation.
7. Verify explicit logout deletes the registration before clearing authentication.
8. Send a Firebase test notification to a physical Android device.
9. Verify foreground, background, and killed-app display and tap behavior.
10. Verify tapping selects the payload establishment and opens Food Stock.

Do not enable iOS sending until the Xcode project, Firebase package references, APNs
entitlements, and per-environment plist wiring are versioned and physically tested.

## 7. In-process schedule and silent hours

The FastAPI lifespan starts an APScheduler job in every server process. PostgreSQL advisory
locking admits only one process at a time, including across Uvicorn workers, Railway
replicas, and overlapping deployments. The notification tables' row locks, uniqueness
constraints, and delivery leases remain the durable work-level safeguards.

Runs begin on each clock hour from **08:00 through 22:00 ART** using the IANA timezone
`America/Argentina/Buenos_Aires`. The silent window is **23:00 through 07:59 ART**. Due
work accumulated overnight is processed from 08:00 onward; no external service needs to
wake the application.

Keep Railway Serverless/App Sleep disabled for the backend: a sleeping container cannot
fire an in-process timer. Configure enough deployment draining time for an active run to
finish gracefully.

There is no public or internal HTTP trigger and no cron secret to provision or rotate.

## 8. Final test checklist

- [ ] Test and production use separate Firebase projects and service-account keys.
- [ ] FCM HTTP v1 is enabled in both Firebase projects.
- [ ] Each Railway environment contains all four backend variables.
- [ ] Both private keys are sealed in Railway.
- [ ] Each Android flavor uses the matching `google-services.json`.
- [ ] The migration is applied before mobile rollout.
- [ ] Backend logs confirm the scheduler starts with ART active hours `8-22`.
- [ ] Railway Serverless/App Sleep is disabled.
- [ ] Device registration and unregister-before-logout work on a physical device.
- [ ] Foreground, background, and killed-app notifications work.
- [ ] Notification taps open Food Stock for the payload establishment.
- [ ] A scheduled active-hour run completes after all earlier checks pass.

## 9. Rotation and incident response

If the service-account key might have leaked:

1. Disable the affected key in Google Cloud immediately.
2. Create a replacement key.
3. Update the corresponding sealed `FCM_PRIVATE_KEY`, `FCM_CLIENT_EMAIL`, and
   `FCM_PROJECT_ID` values in Railway if necessary.
4. Redeploy and verify scheduler startup and the next active-hour run in backend logs.
5. Delete the old key after confirming the replacement works.
