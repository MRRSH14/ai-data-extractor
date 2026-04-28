def build_quality_metadata(schema: dict, result: dict) -> dict:
    total_fields = len(schema)
    extracted_fields = len(result)
    required_fields = 0
    extracted_required_fields = 0
    field_presence: dict[str, bool] = {}

    for field_name, descriptor in schema.items():
        has_value = field_name in result
        field_presence[field_name] = has_value
        if isinstance(descriptor, dict) and bool(descriptor.get("required", False)):
            required_fields += 1
            if has_value:
                extracted_required_fields += 1

    coverage_ratio = 1.0 if total_fields == 0 else round(extracted_fields / total_fields, 4)
    required_coverage_ratio = (
        1.0 if required_fields == 0 else round(extracted_required_fields / required_fields, 4)
    )

    return {
        "coverage": {
            "schema_fields_total": total_fields,
            "schema_fields_extracted": extracted_fields,
            "ratio": coverage_ratio,
        },
        "required_coverage": {
            "required_fields_total": required_fields,
            "required_fields_extracted": extracted_required_fields,
            "ratio": required_coverage_ratio,
        },
        "field_presence": field_presence,
    }


# Backward-compatible alias for existing imports/tests
_build_quality_metadata = build_quality_metadata
