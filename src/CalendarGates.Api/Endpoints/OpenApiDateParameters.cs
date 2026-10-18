using Microsoft.AspNetCore.OpenApi;
using Microsoft.OpenApi;

namespace CalendarGates.Api.Endpoints;

/// <summary>
/// Tells the OpenAPI document the truth about the date parameters (docs/v2-review-findings F086).
///
/// The handlers take them as <c>string</c> and parse them, deliberately: an <c>int?</c> or
/// <c>DateOnly?</c> fails model binding before the validation filter runs, which answered a bad
/// value with a 400 carrying no <c>errors</c> in Production and a 500 in Development (F081). The
/// cost is a schema that said "string" with no format, and — because <c>from</c>/<c>to</c> are
/// nullable so the handler can report both — that they were optional, when a request without them
/// is a 400. This puts the format and the requirement back, without changing the binding.
/// </summary>
internal static class OpenApiDateParameters
{
    /// <summary>Parameters that take `YYYY-MM-DD`, and whether the handler requires one.</summary>
    private static readonly Dictionary<string, bool> _dates = new(StringComparer.Ordinal)
    {
        ["date"] = true, // /api/week/{date}: a route parameter, already required
        ["from"] = true, // /api/workdays: the handler answers a missing one with a 400
        ["to"] = true,
    };

    public static Task Transform(
        OpenApiOperation operation,
        OpenApiOperationTransformerContext context,
        CancellationToken cancellationToken
    )
    {
        // The list holds IOpenApiParameter, whose Required and Schema are read-only; the concrete
        // OpenApiParameter the generator produced is what carries the setters.
        foreach (var parameter in (operation.Parameters ?? []).OfType<OpenApiParameter>())
        {
            if (parameter.Name is null || !_dates.TryGetValue(parameter.Name, out var required))
            {
                continue;
            }

            parameter.Required = required;
            if (parameter.Schema is OpenApiSchema schema)
            {
                schema.Format = "date";
            }
        }

        return Task.CompletedTask;
    }
}
