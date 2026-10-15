using System.ComponentModel.DataAnnotations;
using CalendarGates.Api.Domain;
using Microsoft.AspNetCore.Http.HttpResults;

namespace CalendarGates.Api.Endpoints;

public sealed record LeapResponse(int Year, bool IsLeap);

public static class LeapEndpoints
{
    public static IEndpointRouteBuilder MapLeapEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/leap/{year:int}", ForYear)
            .WithTags("Leap years")
            .WithName("GetLeapYear")
            .WithSummary("Whether a year is a Gregorian leap year");
        return app;
    }

    private static Ok<LeapResponse> ForYear([Range(Years.Min, Years.Max)] int year) =>
        TypedResults.Ok(new LeapResponse(year, LeapYearCalculator.IsLeap(year)));
}
