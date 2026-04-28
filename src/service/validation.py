from shared import ErrorCode, json_response, logger

MAX_TEXT_LENGTH = 32768
MAX_SCHEMA_FIELDS = 20
ALLOWED_SCHEMA_TYPES = {"string", "number", "boolean"}


def validation_error(
    correlation_id: str,
    message: str,
    *,
    error_code: str = ErrorCode.VALIDATION_ERROR,
) -> dict:
    logger.warning(
        message,
        extra={
            "component": "api",
            "correlation_id": correlation_id,
            "event": "validation_error",
            "error_code": error_code,
        },
    )
    return json_response(400, {"error": message, "error_code": error_code})


def validate_extract_input(input_value: object, *, correlation_id: str) -> dict | None:
    if not isinstance(input_value, dict):
        return validation_error(
            correlation_id, "input must be an object", error_code=ErrorCode.INPUT_CONTRACT
        )

    mode = input_value.get("mode")
    if mode != "text":
        return validation_error(
            correlation_id, 'input.mode must be "text"', error_code=ErrorCode.INPUT_CONTRACT
        )

    text = input_value.get("text")
    if not isinstance(text, str):
        return validation_error(
            correlation_id, "input.text must be a string", error_code=ErrorCode.INPUT_CONTRACT
        )
    if not text.strip():
        return validation_error(
            correlation_id, "input.text must be non-empty", error_code=ErrorCode.INPUT_CONTRACT
        )
    if len(text) > MAX_TEXT_LENGTH:
        return validation_error(
            correlation_id,
            f"input.text exceeds max length of {MAX_TEXT_LENGTH}",
            error_code=ErrorCode.INPUT_CONTRACT,
        )

    schema = input_value.get("schema")
    if not isinstance(schema, dict) or not schema:
        return validation_error(
            correlation_id,
            "input.schema must be a non-empty object",
            error_code=ErrorCode.SCHEMA_INVALID,
        )
    if len(schema) > MAX_SCHEMA_FIELDS:
        return validation_error(
            correlation_id,
            f"input.schema exceeds max fields of {MAX_SCHEMA_FIELDS}",
            error_code=ErrorCode.SCHEMA_INVALID,
        )

    for field_name, descriptor in schema.items():
        if not isinstance(field_name, str) or not field_name.strip():
            return validation_error(
                correlation_id,
                "input.schema field names must be non-empty strings",
                error_code=ErrorCode.SCHEMA_INVALID,
            )
        if not isinstance(descriptor, dict):
            return validation_error(
                correlation_id,
                f'input.schema["{field_name}"] must be an object',
                error_code=ErrorCode.SCHEMA_INVALID,
            )

        field_type = descriptor.get("type")
        if field_type not in ALLOWED_SCHEMA_TYPES:
            return validation_error(
                correlation_id,
                f'input.schema["{field_name}"].type must be one of {sorted(ALLOWED_SCHEMA_TYPES)}',
                error_code=ErrorCode.SCHEMA_INVALID,
            )

        description = descriptor.get("description")
        if description is not None and not isinstance(description, str):
            return validation_error(
                correlation_id,
                f'input.schema["{field_name}"].description must be a string when provided',
                error_code=ErrorCode.SCHEMA_INVALID,
            )

        required = descriptor.get("required")
        if required is not None and not isinstance(required, bool):
            return validation_error(
                correlation_id,
                f'input.schema["{field_name}"].required must be a boolean when provided',
                error_code=ErrorCode.SCHEMA_INVALID,
            )

        min_length = descriptor.get("min_length")
        max_length = descriptor.get("max_length")
        minimum = descriptor.get("minimum")
        maximum = descriptor.get("maximum")

        if field_type == "string":
            if min_length is not None and (
                not isinstance(min_length, int) or isinstance(min_length, bool) or min_length < 0
            ):
                return validation_error(
                    correlation_id,
                    f'input.schema["{field_name}"].min_length must be a non-negative integer when provided',
                    error_code=ErrorCode.SCHEMA_INVALID,
                )
            if max_length is not None and (
                not isinstance(max_length, int) or isinstance(max_length, bool) or max_length < 0
            ):
                return validation_error(
                    correlation_id,
                    f'input.schema["{field_name}"].max_length must be a non-negative integer when provided',
                    error_code=ErrorCode.SCHEMA_INVALID,
                )
            if (
                isinstance(min_length, int)
                and not isinstance(min_length, bool)
                and isinstance(max_length, int)
                and not isinstance(max_length, bool)
                and min_length > max_length
            ):
                return validation_error(
                    correlation_id,
                    f'input.schema["{field_name}"].min_length cannot exceed max_length',
                    error_code=ErrorCode.SCHEMA_INVALID,
                )
        elif field_type == "number":
            if minimum is not None and (
                not isinstance(minimum, (int, float)) or isinstance(minimum, bool)
            ):
                return validation_error(
                    correlation_id,
                    f'input.schema["{field_name}"].minimum must be a number when provided',
                    error_code=ErrorCode.SCHEMA_INVALID,
                )
            if maximum is not None and (
                not isinstance(maximum, (int, float)) or isinstance(maximum, bool)
            ):
                return validation_error(
                    correlation_id,
                    f'input.schema["{field_name}"].maximum must be a number when provided',
                    error_code=ErrorCode.SCHEMA_INVALID,
                )
            if (
                isinstance(minimum, (int, float))
                and not isinstance(minimum, bool)
                and isinstance(maximum, (int, float))
                and not isinstance(maximum, bool)
                and minimum > maximum
            ):
                return validation_error(
                    correlation_id,
                    f'input.schema["{field_name}"].minimum cannot exceed maximum',
                    error_code=ErrorCode.SCHEMA_INVALID,
                )

        enum = descriptor.get("enum")
        if enum is not None:
            if not isinstance(enum, list) or not enum:
                return validation_error(
                    correlation_id,
                    f'input.schema["{field_name}"].enum must be a non-empty array when provided',
                    error_code=ErrorCode.SCHEMA_INVALID,
                )
            if field_type == "string":
                if not all(isinstance(v, str) for v in enum):
                    return validation_error(
                        correlation_id,
                        f'input.schema["{field_name}"].enum must contain only strings',
                        error_code=ErrorCode.SCHEMA_INVALID,
                    )
            elif field_type == "number":
                if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in enum):
                    return validation_error(
                        correlation_id,
                        f'input.schema["{field_name}"].enum must contain only numbers',
                        error_code=ErrorCode.SCHEMA_INVALID,
                    )
            elif field_type == "boolean":
                if not all(isinstance(v, bool) for v in enum):
                    return validation_error(
                        correlation_id,
                        f'input.schema["{field_name}"].enum must contain only booleans',
                        error_code=ErrorCode.SCHEMA_INVALID,
                    )

    return None
