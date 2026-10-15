using CalendarGates.Api.Domain;
using Microsoft.AspNetCore.Http.HttpResults;

namespace CalendarGates.Api.Endpoints;

public sealed record WorkdaysResponse(DateOnly From, DateOnly To, int Workdays);

public static class WorkdaysEndpoints
{
    public static IEndpointRouteBuilder MapWorkdaysEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/workdays", Count)
            .WithTags("Workdays")
            .WithName("GetWorkdays")
            .WithSummary("Monday–Friday days between two dates, both inclusive");
        return app;
    }

    private static Results<Ok<WorkdaysResponse>, ValidationProblem> Count(string? from, string? to)
    {
        var errors = new Dictionary<string, string[]>();
        if (!EndpointHelpers.TryParseDate(from, out var start))
        {
            errors["from"] = [EndpointHelpers.InvalidDateMessage(from)];
        }

        if (!EndpointHelpers.TryParseDate(to, out var end))
        {
            errors["to"] = [EndpointHelpers.InvalidDateMessage(to)];
        }

        if (errors.Count == 0)
        {
            var limit =
                start.Year <= DateOnly.MaxValue.Year - WorkdaysCalculator.MaxSpanYears
                    ? start.AddYears(WorkdaysCalculator.MaxSpanYears)
                    : DateOnly.MaxValue;
            if (end < start)
            {
                errors["to"] = ["'to' must not be before 'from'."];
            }
            else if (end > limit)
            {
                errors["to"] =
                [
                    $"The range must not span more than {WorkdaysCalculator.MaxSpanYears} years.",
                ];
            }
        }

        return errors.Count > 0
            ? TypedResults.ValidationProblem(errors)
            : TypedResults.Ok(
                new WorkdaysResponse(start, end, WorkdaysCalculator.Count(start, end))
            );
    }
}
