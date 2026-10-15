using CalendarGates.Api.Domain;
using Microsoft.AspNetCore.Http.HttpResults;

namespace CalendarGates.Api.Endpoints;

public static class WeekEndpoints
{
    public static IEndpointRouteBuilder MapWeekEndpoints(this IEndpointRouteBuilder app)
    {
        var group = app.MapGroup("/week").WithTags("Week");
        group.MapGet("", Current).WithName("GetCurrentWeek").WithSummary("ISO week of today (UTC)");
        group.MapGet("/{date}", ForDate).WithName("GetWeek").WithSummary("ISO week of a date");
        return app;
    }

    private static Ok<IsoWeekInfo> Current(TimeProvider time) =>
        TypedResults.Ok(IsoWeekCalculator.For(time.Today()));

    private static Results<Ok<IsoWeekInfo>, ValidationProblem> ForDate(string date) =>
        EndpointHelpers.TryParseDate(date, out var parsed)
            ? TypedResults.Ok(IsoWeekCalculator.For(parsed))
            : TypedResults.ValidationProblem(
                new Dictionary<string, string[]>
                {
                    ["date"] = [EndpointHelpers.InvalidDateMessage(date)],
                }
            );
}
