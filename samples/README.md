# Quick evaluation samples

Use these files to quickly evaluate the API contract and terminal task outcomes.

## Request payloads

- `requests/text_extract_invoice.json` - text-mode extraction request.
- `requests/file_extract_s3_invoice.json` - file-mode extraction request using S3 object reference.

## Expected terminal examples

- `expected/completed_task_text.json` - representative successful `GET /tasks/{id}` response.
- `expected/failed_task_missing_s3_key.json` - deterministic file-mode input-contract failure.
- `expected/failed_task_non_utf8_text_file.json` - deterministic UTF-8 decode failure for text-like file.

## How to use

1. Create a task:
   - `curl -X POST "$API_URL/tasks" -H "Authorization: Bearer $TEST_ID_TOKEN" -H "Content-Type: application/json" -d @samples/requests/text_extract_invoice.json`
2. Poll `GET /tasks/{id}` until terminal state.
3. Compare with `samples/expected/*.json`.
