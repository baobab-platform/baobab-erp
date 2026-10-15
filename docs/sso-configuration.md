# iDempiere SSO Configuration (Gate IAM-10, ADR-0014)

iDempiere 13 ships a real, pluggable, built-in OIDC mechanism (`org.idempiere.ui.sso.oidc`,
part of its `core` distribution feature — verified directly against `idempiere/idempiere`'s
own source, not assumed). No plugin install step is needed: it's already in the pinned
`idempiereofficial/idempiere:13-release` image this repository builds from.

## Why this is a runbook, not a migration script

`AD_SSO_PrincipalConfig` lives in iDempiere's own `adempiere` schema. Per `db/README.md`
and ADR-ERP-001, "Neither engine's code reads or writes the other's schema directly ...
only iDempiere touches its own tables" — a checked-in SQL script inserting into that
table from this repository's own migration tooling (`db/migrations/`, which only ever
touches the separate `baobab` schema) would violate that boundary. Configuring SSO is
therefore a System Administrator task performed inside iDempiere itself, documented here
rather than automated.

## Steps

1. Log in to iDempiere as **System Administrator** (the native local login — this is the
   one case ADR-0014 §41-43 expects to remain, as a break-glass path, not routine access).
2. Open **General Rules > System Rules > System > SSO Configuration** (backed by the
   `AD_SSO_PrincipalConfig` window/table).
3. Create a new record with:

   | Field | Value |
   |---|---|
   | SSO Provider | OIDC |
   | Application Client ID | `baobab-erp-admin` (the Keycloak client `nabhold/baobab-iam`'s `config/clients/baobab-erp-admin.json` provisions) |
   | Application Secret Key | The `baobab-erp-admin` client secret from Baobab IAM's Keycloak Admin Console, injected via this deployment's own secrets management. **Never commit this value anywhere.** |
   | Application Discovery URI | `<Baobab IAM issuer>/.well-known/openid-configuration`, e.g. `https://iam.example.com/realms/baobab/.well-known/openid-configuration` |
   | Application Redirect URIs | The iDempiere WebUI's own externally-reachable URL, e.g. `https://erp.example.com/webui/` for production, or `https://localhost:8443/webui/` for local dev (must exactly match an entry in `baobab-erp-admin`'s `redirectUris`) |

4. Leave the IDempMonitor/OSGI redirect fields empty unless those surfaces are also
   wired to SSO — this gate only covers the WebUI login path.
5. Save and activate the record.

## What to expect

- The iDempiere login screen shows an SSO login option that redirects to Baobab IAM,
  authenticates there (including any MFA Baobab IAM enforces), and returns.
- iDempiere resolves the returned identity to an **existing** `AD_User` by matching
  either its email or username claim (controlled by iDempiere's own
  `USE_EMAIL_FOR_LOGIN` system configuration) against that user's iDempiere login name —
  **not** by `issuer+subject`. See
  `docs/governance/gate-iam-10-erp-integration-scope.md` §2 in `nabhold/baobab-iam` for
  why this specific, bounded deviation from ADR-0014 §9 was accepted rather than blocking
  on a custom integration.
- There is no auto-creation: a person with no existing, matching `AD_User` cannot log in
  via SSO at all (ADR-0014 §11-13's no-auth-equals-provisioning invariant holds).
  Provisioning a new `AD_User` remains a separate, explicit administrative act.

## Machine callers: the OSGi bundles' own workload authentication

The steps above cover **human** WebUI login. Separately, `context`/`mapping`'s own
OSGi bundles (running inside iDempiere's JVM, calling baobab-app's HTTP API to reach
the `baobab` Postgres schema) now authenticate as the `baobab-erp-workload` machine
identity, since baobab-app's `/context/resolve*`/`/mapping/resolve*` no longer trust
network location alone (ADR-0014 §111). This needs three JVM system properties passed
to iDempiere's own launch (see `idempiere/README.md`):

- `baobab.iam.token.url`
- `baobab.iam.workload.client.secret` (the `baobab-erp-workload` client's secret from
  Baobab IAM's Keycloak Admin Console — **never commit this value**)
  — preferably as `baobab.iam.workload.client.secret.file`, the path of a mounted secret
  file, because iDempiere's start script echoes inline `-D` values to its log
- `baobab.iam.token.url`'s companions `baobab.iam.workload.client.id` and
  `baobab.iam.workload.scope` default to `baobab-erp-workload`/`erp:integrate` and
  rarely need overriding.

If `baobab.iam.workload.client.secret` is left unset, every context/mapping call from
inside iDempiere fails loudly with a 401 from baobab-app rather than silently bypassing
authentication — check for that specifically if context/mapping resolution stops
working after upgrading past Gate IAM-10.

## What this does not cover

- **Role/AD_Client/AD_Org selection after login** — unaffected by this configuration;
  iDempiere's own native post-login role picker still applies (ADR-0014 §32-33).
- **MFA/step-up for finance users** — enforced by Baobab IAM's own realm policy
  (Gate IAM-11, ADR-0015), not by anything in this file.
- **Local account migration** — not applicable yet; see
  `docs/governance/gate-iam-10-erp-integration-scope.md` §5.
