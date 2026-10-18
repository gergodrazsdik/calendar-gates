using System.Globalization;
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
            .WithSummary("Next Friday the 13th on or after today (UTC)")
            // There is none after 9999-08-13, and the handler's return type doesn't say so (F111).
            .Produces(StatusCodes.Status404NotFound);
        return app;
    }

    // `string?`, not `int?`: an unparsable value bound to an int fails parameter binding before the
    // validation filter runs, which answered `?year=abc` with a 400 carrying no `errors` in
    // Production and a 500 in Development (F081). Parsed here, every bad year is one ValidationProblem.
    private static Results<Ok<Friday13YearResponse>, ValidationProblem> InYear(
        string? year,
        TimeProvider time
    )
    {
        if (!string.IsNullOrEmpty(year) && !EndpointHelpers.TryParseYear(year, out _))
        {
            return TypedResults.ValidationProblem(
                new Dictionary<string, string[]>
                {
                    ["year"] = [EndpointHelpers.InvalidYearMessage(year)],
                }
            );
        }

        var y = string.IsNullOrEmpty(year)
            ? time.Today().Year
            : int.Parse(year, CultureInfo.InvariantCulture);
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
