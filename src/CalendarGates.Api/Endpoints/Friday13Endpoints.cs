using System.ComponentModel.DataAnnotations;
using CalendarGates.Api.Domain;
using Microsoft.AspNetCore.Http.HttpResults;

namespace CalendarGates.Api.Endpoints;

public sealed record Friday13YearResponse(int Year, int Count, IReadOnlyList<DateOnly> Dates);

public sealed record Friday13NextResponse(DateOnly Date, int DaysUntil);

public static class Friday13Endpoints
{
    public static IEndpointRouteBuilder MapFriday13Endpoints(this IEndpointRouteBuilder app)
    {
        var group = app.MapGroup("/friday13").WithTags("Friday the 13th");
        group
            .MapGet("", InYear)
            .WithName("GetFriday13s")
            .WithSummary("Fridays the 13th in a year (default: this year)")
            .ProducesValidationProblem();
        group
            .MapGet("/next", Next)
            .WithName("GetNextFriday13")
            .WithSummary("Next Friday the 13th on or after today (UTC)");
        return app;
    }

    private static Ok<Friday13YearResponse> InYear(
        [Range(Years.Min, Years.Max)] int? year,
        TimeProvider time
    )
    {
        var y = year ?? time.Today().Year;
        var dates = Friday13Calculator.InYear(y);
        return TypedResults.Ok(new Friday13YearResponse(y, dates.Count, dates));
    }

    private static Results<Ok<Friday13NextResponse>, NotFound> Next(TimeProvider time)
    {
        var today = time.Today();
        return Friday13Calculator.NextOnOrAfter(today) is { } next
            ? TypedResults.Ok(new Friday13NextResponse(next, next.DayNumber - today.DayNumber))
            : TypedResults.NotFound();
    }
}
