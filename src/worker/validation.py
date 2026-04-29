from decimal import Decimal, InvalidOperation

from shared import ErrorCode
from worker.errors import non_retryable


def validate_extract_payload(payload: dict) -> tuple[dict, dict]:
    job_type = payload.get("job_type")
    if job_type != "extract":
        raise non_retryable(ErrorCode.INPUT_CONTRACT, 'job_type must be "extract"')

    input_value = payload.get("input")
    if not isinstance(input_value, dict):
        raise non_retryable(ErrorCode.INPUT_CONTRACT, "input must be an object")

    mode = input_value.get("mode")
    if mode == "text":
        text = input_value.get("text")
        if not isinstance(text, str) or not text.strip():
            raise non_retryable(ErrorCode.INPUT_CONTRACT, "input.text must be a non-empty string")
        input_spec = {"mode": "text", "text": text}
    elif mode == "file":
        file_ref = input_value.get("file")
        if not isinstance(file_ref, dict):
            raise non_retryable(
                ErrorCode.INPUT_CONTRACT,
                "input.file must be an object when input.mode is \"file\"",
            )
        if file_ref.get("source") != "s3":
            raise non_retryable(ErrorCode.INPUT_CONTRACT, 'input.file.source must be "s3"')
        bucket = file_ref.get("bucket")
        if not isinstance(bucket, str) or not bucket.strip():
            raise non_retryable(
                ErrorCode.INPUT_CONTRACT,
                "input.file.bucket must be a non-empty string",
            )
        key = file_ref.get("key")
        if not isinstance(key, str) or not key.strip():
            raise non_retryable(
                ErrorCode.INPUT_CONTRACT,
                "input.file.key must be a non-empty string",
            )
        input_spec = {"mode": "file", "file": {"bucket": bucket, "key": key}}
    else:
        raise non_retryable(
            ErrorCode.INPUT_CONTRACT,
            'input.mode must be either "text" or "file"',
        )

    schema = input_value.get("schema")
    if not isinstance(schema, dict) or not schema:
        raise non_retryable(ErrorCode.INPUT_CONTRACT, "input.schema must be a non-empty object")

    return input_spec, schema


def coerce_and_validate_result(raw_result: object, schema: dict) -> dict:
    if not isinstance(raw_result, dict):
        raise non_retryable(ErrorCode.MODEL_OUTPUT_INVALID, "model output must be a JSON object")

    normalized: dict = {}
    for field_name, descriptor in schema.items():
        if not isinstance(field_name, str) or not field_name.strip():
            raise non_retryable(ErrorCode.SCHEMA_INVALID, "schema field names must be non-empty strings")
        if not isinstance(descriptor, dict):
            raise non_retryable(
                ErrorCode.SCHEMA_INVALID,
                f'schema descriptor for "{field_name}" must be an object',
            )

        field_type = descriptor.get("type")
        required = bool(descriptor.get("required", False))
        enum_values = descriptor.get("enum")
        min_length = descriptor.get("min_length")
        max_length = descriptor.get("max_length")
        minimum = descriptor.get("minimum")
        maximum = descriptor.get("maximum")
        value = raw_result.get(field_name)
        if value is None:
            if required:
                raise non_retryable(
                    ErrorCode.SCHEMA_VALIDATION,
                    f'required field "{field_name}" missing from model output',
                )
            continue

        if field_type == "string":
            if not isinstance(value, str):
                value = str(value)
            if min_length is not None:
                if not isinstance(min_length, int) or isinstance(min_length, bool) or min_length < 0:
                    raise non_retryable(
                        ErrorCode.SCHEMA_INVALID,
                        f'schema min_length for "{field_name}" must be a non-negative integer',
                    )
                if len(value) < min_length:
                    raise non_retryable(
                        ErrorCode.SCHEMA_VALIDATION,
                        f'field "{field_name}" length must be >= {min_length}',
                    )
            if max_length is not None:
                if not isinstance(max_length, int) or isinstance(max_length, bool) or max_length < 0:
                    raise non_retryable(
                        ErrorCode.SCHEMA_INVALID,
                        f'schema max_length for "{field_name}" must be a non-negative integer',
                    )
                if len(value) > max_length:
                    raise non_retryable(
                        ErrorCode.SCHEMA_VALIDATION,
                        f'field "{field_name}" length must be <= {max_length}',
                    )
        elif field_type == "number":
            if isinstance(value, bool):
                raise non_retryable(
                    ErrorCode.SCHEMA_VALIDATION,
                    f'field "{field_name}" must be a number, got boolean',
                )
            if isinstance(value, float):
                value = Decimal(str(value))
            elif not isinstance(value, (int, Decimal)):
                try:
                    value = Decimal(str(value))
                except (TypeError, ValueError, InvalidOperation):
                    raise non_retryable(
                        ErrorCode.SCHEMA_VALIDATION,
                        f'field "{field_name}" must be numeric',
                    ) from None
            if minimum is not None:
                if not isinstance(minimum, (int, float, Decimal)) or isinstance(minimum, bool):
                    raise non_retryable(
                        ErrorCode.SCHEMA_INVALID,
                        f'schema minimum for "{field_name}" must be numeric',
                    )
                if Decimal(str(value)) < Decimal(str(minimum)):
                    raise non_retryable(
                        ErrorCode.SCHEMA_VALIDATION,
                        f'field "{field_name}" must be >= {minimum}',
                    )
            if maximum is not None:
                if not isinstance(maximum, (int, float, Decimal)) or isinstance(maximum, bool):
                    raise non_retryable(
                        ErrorCode.SCHEMA_INVALID,
                        f'schema maximum for "{field_name}" must be numeric',
                    )
                if Decimal(str(value)) > Decimal(str(maximum)):
                    raise non_retryable(
                        ErrorCode.SCHEMA_VALIDATION,
                        f'field "{field_name}" must be <= {maximum}',
                    )
        elif field_type == "boolean":
            if isinstance(value, bool):
                pass
            elif isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "yes", "1"}:
                    value = True
                elif lowered in {"false", "no", "0"}:
                    value = False
                else:
                    raise non_retryable(
                        ErrorCode.SCHEMA_VALIDATION,
                        f'field "{field_name}" must be boolean',
                    )
            else:
                raise non_retryable(
                    ErrorCode.SCHEMA_VALIDATION, f'field "{field_name}" must be boolean'
                )
        else:
            raise non_retryable(
                ErrorCode.SCHEMA_INVALID,
                f'schema type for "{field_name}" must be string, number, or boolean',
            )

        if enum_values is not None:
            if not isinstance(enum_values, list) or not enum_values:
                raise non_retryable(
                    ErrorCode.SCHEMA_INVALID,
                    f'schema enum for "{field_name}" must be a non-empty array',
                )
            if field_type == "number":
                try:
                    normalized_value = value if isinstance(value, Decimal) else Decimal(str(value))
                    normalized_enum = [Decimal(str(v)) for v in enum_values]
                except (TypeError, ValueError, InvalidOperation):
                    raise non_retryable(
                        ErrorCode.SCHEMA_INVALID,
                        f'schema enum for "{field_name}" must contain numeric values',
                    ) from None
                if normalized_value not in normalized_enum:
                    raise non_retryable(
                        ErrorCode.SCHEMA_VALIDATION,
                        f'field "{field_name}" must be one of {enum_values}',
                    )
            elif field_type == "string":
                if not all(isinstance(v, str) for v in enum_values):
                    raise non_retryable(
                        ErrorCode.SCHEMA_INVALID,
                        f'schema enum for "{field_name}" must contain string values',
                    )
                if value not in enum_values:
                    raise non_retryable(
                        ErrorCode.SCHEMA_VALIDATION,
                        f'field "{field_name}" must be one of {enum_values}',
                    )
            else:  # boolean
                if not all(isinstance(v, bool) for v in enum_values):
                    raise non_retryable(
                        ErrorCode.SCHEMA_INVALID,
                        f'schema enum for "{field_name}" must contain boolean values',
                    )
                if value not in enum_values:
                    raise non_retryable(
                        ErrorCode.SCHEMA_VALIDATION,
                        f'field "{field_name}" must be one of {enum_values}',
                    )

        normalized[field_name] = value

    return normalized

