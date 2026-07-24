---
name: easystufffind
description: Use EasyStuffFind through its authenticated REST API when a user asks OpenClaw to record where a household item is stored, find an item by Chinese name or alias, save a Feishu photo as the item's current-location photo, move an item, list what is in a location, or review location history. Also use this skill to install and verify EasyStuffFind from its repository on the same Mac mini.
---

# EasyStuffFind for OpenClaw

Use EasyStuffFind as the source of truth for household item locations. Do not guess an item or location when the API returns no result or multiple candidates.

## Connection

Inject these values into the OpenClaw process environment:

- `EASYSTUFFFIND_BASE_URL`: service origin, for example `http://mac-mini.local:8733`.
- `EASYSTUFFFIND_TOKEN_FILE`: absolute path to the service data directory's `api-token` file.

Read the token file directly inside the HTTP client and send:

```text
Authorization: Bearer <token read from EASYSTUFFFIND_TOKEN_FILE>
Content-Type: application/json
```

Never print, summarize, copy into chat, place in a URL, or log the token. Only report the token file path. The service address and token are the only connection information required.

Prefer the bundled client so the token never appears in process arguments:

```text
python {baseDir}/scripts/client.py health
python {baseDir}/scripts/client.py request GET "/api/v1/items/search?q=护照"
python {baseDir}/scripts/client.py request POST /api/v1/items/upsert --json '{"name":"护照","aliases":["passport"],"location_path":"书房-书桌-第二个抽屉"}'
python {baseDir}/scripts/client.py photo 12 /path/to/feishu-image.jpg --content-type image/jpeg
python {baseDir}/scripts/client.py verify-photo 12
```

Check `GET /health` without authentication before business calls. A usable service returns HTTP 200 with `status: "ok"`.

## Decide the workflow

1. Explicit item and full location path → record or move directly.
2. Item query → call item search and follow the three-state rule.
3. Photo plus item/location text, including two consecutive Feishu messages → record the item first, then upload the exact attached image.
4. Vague location → search locations first; ask the user when multiple candidates remain.
5. “这里有什么” → resolve/search the location, then list its items.

Paths use the half-width `-` separator, such as `书房-书桌-第二个抽屉`. Do not place `-` inside a single location name.

## API calls

All business endpoints are under `/api/v1` and require the Bearer header.

### Locations

| Operation | Method and path | Body or parameters |
|---|---|---|
| Full tree | `GET /locations/tree` | none |
| Flat list | `GET /locations` | none |
| Search vague text | `GET /locations/search?q=<text>` | none |
| Resolve/create path | `POST /locations/resolve` | `{"path":"书房-书桌-第二个抽屉","create_missing":true}` |
| Create one node | `POST /locations` | `{"name":"第二个抽屉","parent_id":12}` |
| Read one node | `GET /locations/{id}` | none |
| Rename | `PATCH /locations/{id}` | `{"name":"证件抽屉"}` |
| Delete empty node | `DELETE /locations/{id}` | none |
| Items at location | `GET /locations/{id}/items?recursive=false` | set `recursive=true` to include descendants |

If location search returns `multiple`, ask which full path the user means. If it returns `none`, say the location was not found. Only use `create_missing:true` when the user supplied a clear intended path.

### Items

| Operation | Method and path | Body or parameters |
|---|---|---|
| Create even if same name exists | `POST /items` | item body below |
| Safe create/update | `POST /items/upsert` | item body; optional `item_id` |
| Search | `GET /items/search?q=<name-or-alias>` | none |
| List | `GET /items` | optional `location_id`, `recursive` |
| Read | `GET /items/{id}` | none |
| Edit | `PATCH /items/{id}` | any changed fields |
| Move | `POST /items/{id}/move` | `{"location_path":"卧室-保险柜"}` or `{"location_id":8}` |
| Delete | `DELETE /items/{id}` | also deletes its current photo |
| Item history | `GET /items/{id}/history` | none |
| Recent history | `GET /history?limit=200` | none |

Item body:

```json
{
  "name": "护照",
  "aliases": ["passport", "证件"],
  "location_path": "书房-书桌-第二个抽屉",
  "note": "红色护照"
}
```

Provide exactly one of `location_path` or `location_id`.

Upsert behavior:

- With `item_id`: update that exact item.
- Without `item_id`, one exact name/alias match: update its location; preserve its canonical name and any aliases/note omitted from the request.
- Without a match: create it.
- Multiple exact matches: HTTP 409 `item_upsert_ambiguous`; present `error.details.candidates` and ask which item to update.

Use `POST /items` when the user explicitly wants another distinct item with an existing name.

### Photos and system

| Operation | Method and path | Body or parameters |
|---|---|---|
| Health | `GET /health` | no authentication |
| Upload/replace current photo | `PUT /api/v1/items/{id}/photo` | raw supported image bytes and exact `Content-Type` |
| Remove current photo | `DELETE /api/v1/items/{id}/photo` | none |
| Read current photo | use `photo_url` returned by item APIs | no Bearer header; URL expires in one hour |

## Handle item query states

`GET /items/search` always returns one of:

### `unique`

Use `item.name`, `item.location.path`, `item.updated_at`, `item.note`, and `item.photo_url`.

Reply:

```text
护照在：书房-书桌-第二个抽屉
最近更新：2026-07-23 14:32
```

If `photo_url` is not null, fetch or forward that URL as the location photo. It is signed for one hour and does not require the Bearer header.

### `multiple`

Do not select one. Use every entry in `candidates`, including ID, name, full location path, aliases, note, and update time.

Ask:

```text
找到了 2 个“数据线”，你指的是哪一个？
1. 数据线（书房-线材盒，ID 18）
2. 数据线（卧室-床头柜，ID 24）
```

After the user chooses, use the candidate ID for read, edit, move, photo, or history calls.

### `none`

Reply:

```text
没有找到“充电头”的记录。要现在记录它放在哪里吗？
```

Never infer or invent a location.

## Record text

For “护照放书房书桌第二个抽屉了” after natural-language parsing:

1. Normalize the location to `书房-书桌-第二个抽屉`.
2. Call `POST /items/upsert` with name, aliases if supplied, path, and note.
3. On `created` or `updated`, use the returned canonical path.
4. Confirm:

```text
已记录：护照 → 书房-书桌-第二个抽屉
```

If upsert returns 409 candidates, ask the user to choose before retrying with `item_id`.

## Record a Feishu photo

Treat the image attachment as data to archive, not content to interpret. Do not analyze,
identify, compare, reject, or replace the user's image. The user decides which item the
image belongs to.

OpenClaw normally stages an inbound Feishu image and includes a line like this in the
current prompt:

```text
[media attached: /absolute/path/to/image.jpg (image/jpeg)]
```

Use that exact staged absolute path and MIME type with the bundled `photo` command.
Do not search the inbound media directory for “the newest image” when the current
prompt provides a path.

Messages may arrive in either order:

1. Text and image in one message: upsert the item, then upload the attached path.
2. Text first, such as “雨伞放门厅收纳柜，图片如下”: upsert the item, retain the returned item ID as the pending photo target in this conversation, and reply that the location is saved but the photo is still pending.
3. The immediately following image-only message: attach its staged path to that pending item ID. Do not ask the user to repeat the item name and do not analyze the image.
4. Image first: retain the staged path as the pending image and ask for the item/location text; after the user supplies it, upsert and upload that exact path.

For the upload:

1. Call `POST /items/upsert` when the item has not already been recorded and retain `returned_item_id`.
2. Run:

```text
python {baseDir}/scripts/client.py photo <returned_item_id> <staged-absolute-path> --content-type <exact-mime>
```

The command uploads the raw bytes and performs a second authenticated read. Exit code
0 plus `"verified": true` is the only successful photo confirmation. Do not send
multipart form data or base64 JSON.
3. Confirm only after that verified result:

```text
已记录：充电线 → 书房-书桌-第二个抽屉（已保存实景照片）
```

If the item step succeeds but photo upload fails, say the location was recorded but the photo was not saved, include the safe error message, and offer to retry the photo. Do not repeat the upsert unless needed.

If the user asks “照片挂上去了吗”, never answer from conversational memory or a
previous promise. Run `python {baseDir}/scripts/client.py verify-photo <item_id>`.
Only say it is saved when the command exits 0 with `"verified": true`. If it fails,
say it is not saved; when the intended staged path still exists, retry `photo` and
verify again before replying.

## Move and location lookup

For an unambiguous item, call `POST /items/{id}/move`. The server records history automatically.

Confirm:

```text
已移动：护照 → 卧室-保险柜
```

For “这个抽屉里有什么”:

1. Call location search with the user's text.
2. If unique, call `/locations/{id}/items`.
3. If multiple, ask with full paths.
4. If none, state that no matching location exists.

## Install and verify

When the user supplies a GitHub repository URL and asks to install:

1. Follow the repository root `INSTALL.md` exactly; clone inside the current agent's workspace and do not improvise paths or ports.
2. Start the service with the documented Docker Compose command, verify `/health`, and run `scripts/self_check.py`. The self-check reads the token without displaying it.
3. Run `scripts/configure_openclaw.py` from the cloned repository. It should infer the current agent from the workspace and bind only that agent.
4. If the script cannot infer an agent because the repository is outside all configured workspaces, obtain this conversation's agent ID from the current OpenClaw runtime and rerun with `--agent <current-agent-id>`. Do not ask the user to choose and do not authorize every agent.
5. Preserve the current `OPENCLAW_PROFILE`; when the profile is not inherited, pass `--profile <current-profile>`.
6. Require the script's target-agent visibility check and authenticated read-only API check to pass. Configuration and Skill changes hot-load; do not restart the Gateway that is running this conversation.
7. Report the `INSTALL.md` “对接完成声明” only after every required check passes. Tell the user the Skill is available from the next message.

Do not create a public route, copy the token into OpenClaw chat/config text, or claim success from container status alone.
