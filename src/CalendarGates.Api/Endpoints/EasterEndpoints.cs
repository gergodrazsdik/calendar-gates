using System.ComponentModel.DataAnnotations;
using CalendarGates.Api.Domain;
using Microsoft.AspNetCore.Http.HttpResults;

namespace CalendarGates.Api.Endpoints;

public sealed record EasterResponse(int Year, DateOnly Western, DateOnly Orthodox);

public static class EasterEndpoints
{
    public static IEndpointRouteBuilder MapEasterEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/easter/{year:int}", ForYear)
            .WithTags("Easter")
            .WithName("GetEaster")
            .WithSummary("Western and Orthodox Easter Sunday (Gregorian dates)")
            // The validation filter answers an out-of-range year with a ValidationProblem; the
            // handler's return type can't show that, so declare it (docs/v2-review-findings F082).
            .ProducesValidationProblem();
        return app;
    }

    private static Ok<EasterResponse> ForYear([Range(Years.Min, Years.Max)] int year) =>
        TypedResults.Ok(
            new EasterResponse(
                year,
                EasterCalculator.Western(year),
                EasterCalculator.Orthodox(year)
            )
        );
}
