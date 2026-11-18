// capacity-insights — Power Query (M) loader for Power BI Desktop
// ---------------------------------------------------------------------------
// Paste into Power BI Desktop: Home > Get Data > Blank Query >
// Advanced Editor, replace the whole text, name the query "Utilization".
// Point Source at the CSV produced by the Python pipeline, e.g.
//   python -m capacity_insights generate --output sample.csv
// or your own export with the same columns:
//   timestamp, resource, host, app_team, metric, value

let
    Source = Csv.Document(
        File.Contents("C:\data\sample.csv"),
        [Delimiter = ",", Columns = 6, Encoding = 65001, QuoteStyle = QuoteStyle.None]
    ),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"timestamp", type date},
        {"resource", type text},
        {"host", type text},
        {"app_team", type text},
        {"metric", type text},
        // value is a percent number in the CSV (62.5 means 62.5%), matching
        // the DAX measures in this folder — keep it as a plain number.
        {"value", type number}
    }),
    Sorted = Table.Sort(Typed, {{"resource", Order.Ascending},
                                   {"metric", Order.Ascending},
                                   {"timestamp", Order.Ascending}})
in
    Sorted

// Optional second query "Params" (Enter Data, one row):
//   Threshold = 80, HorizonDays = 90
// The DAX measures read it with SELECTEDVALUE and fall back to 80 / 90.
