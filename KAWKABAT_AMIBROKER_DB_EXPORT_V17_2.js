// KAWKABAT AmiBroker DB Exporter V17.2
// External WSH JScript. Data-only: Stocks -> Stock -> Quotations.
// No ActiveWindow, no chart switching, no ExportImage.

(function () {
    var fso = new ActiveXObject("Scripting.FileSystemObject");
    var runtimeDir = "C:\\KawkabatSeherAlarqam\\runtime";
    var requestFile = runtimeDir + "\\chart_request.txt";

    var mode = WScript.Arguments.length > 0 ? String(WScript.Arguments(0)) : "default";
    var csvFile = runtimeDir + "\\amibroker-db-export-v172-" + mode + ".csv";
    var tmpFile = runtimeDir + "\\amibroker-db-export-v172-" + mode + ".tmp";
    var statusFile = runtimeDir + "\\amibroker-db-status-v172-" + mode + ".txt";

    if (!fso.FolderExists(runtimeDir)) fso.CreateFolder(runtimeDir);

    var lastSymbol = "";
    var lastCount = -1;
    var lastExportAt = 0;

    function readSymbol() {
        var s = "XAUUSD";
        try {
            if (fso.FileExists(requestFile)) {
                var h = fso.OpenTextFile(requestFile, 1, false);
                s = String(h.ReadAll()).replace(/^\s+|\s+$/g, "").toUpperCase();
                h.Close();
                if (!s) s = "XAUUSD";
            }
        } catch (e) {}
        return s;
    }

    function pad2(n) {
        return (n < 10 ? "0" : "") + n;
    }

    function isoDate(d) {
        return d.getFullYear() + "-" +
               pad2(d.getMonth() + 1) + "-" +
               pad2(d.getDate()) + "T" +
               pad2(d.getHours()) + ":" +
               pad2(d.getMinutes()) + ":" +
               pad2(d.getSeconds());
    }

    function cleanNum(v) {
        var n = Number(v);
        if (!isFinite(n)) return "0";
        return String(n);
    }

    function writeStatus(stage, symbol, quotesCount, rowsWritten, dbPath, errorText) {
        try {
            var h = fso.OpenTextFile(statusFile, 2, true);
            h.WriteLine("version=17.2");
            h.WriteLine("mode=" + mode);
            h.WriteLine("stage=" + stage);
            h.WriteLine("symbol=" + symbol);
            h.WriteLine("quotes_count=" + quotesCount);
            h.WriteLine("rows_written=" + rowsWritten);
            h.WriteLine("database_path=" + dbPath);
            h.WriteLine("error=" + String(errorText || "").replace(/\r|\n/g, " "));
            h.WriteLine("time=" + (new Date()).toString());
            h.Close();
        } catch (e) {}
    }

    function atomicFinish() {
        try {
            if (fso.FileExists(csvFile)) fso.DeleteFile(csvFile, true);
            fso.MoveFile(tmpFile, csvFile);
        } catch (e) {
            try {
                fso.CopyFile(tmpFile, csvFile, true);
                fso.DeleteFile(tmpFile, true);
            } catch (e2) {}
        }
    }

    function exportSymbol(symbol) {
        var AB = null;
        var dbPath = "";
        var rowsWritten = 0;
        var qty = 0;

        try {
            writeStatus("CONNECT", symbol, 0, 0, "", "");

            // Official AmiBroker automation pattern.
            AB = WScript.CreateObject("Broker.Application");
            dbPath = String(AB.DatabasePath || "");

            var stocks = AB.Stocks;
            var stock = stocks(symbol);
            if (!stock) {
                writeStatus("NO_STOCK", symbol, 0, 0, dbPath, "Ticker not found in AmiBroker database");
                return { ok:false, count:0 };
            }

            var quotes = stock.Quotations;
            qty = Number(quotes.Count || 0);

            if (!qty) {
                writeStatus("NO_QUOTES", symbol, 0, 0, dbPath, "Quotation count is zero");
                return { ok:false, count:0 };
            }

            writeStatus("EXPORTING", symbol, qty, 0, dbPath, "");

            var file = fso.OpenTextFile(tmpFile, 2, true);
            file.WriteLine("symbol,timestamp,open,high,low,close,volume");

            // Export all quotations on symbol change.
            // On periodic refresh, exporting all still guarantees exact DB state
            // and is safe; the service only runs when count/symbol changes or every 30s.
            for (var i = 0; i < qty; i++) {
                var q = quotes(i);
                if (!q) continue;

                var d = new Date(q.Date);
                if (isNaN(d.getTime())) continue;

                file.WriteLine(
                    symbol + "," +
                    isoDate(d) + "," +
                    cleanNum(q.Open) + "," +
                    cleanNum(q.High) + "," +
                    cleanNum(q.Low) + "," +
                    cleanNum(q.Close) + "," +
                    cleanNum(q.Volume)
                );
                rowsWritten++;
            }

            file.Close();

            if (rowsWritten > 0) {
                atomicFinish();
                writeStatus("COMPLETE", symbol, qty, rowsWritten, dbPath, "");
                return { ok:true, count:qty };
            }

            writeStatus("EMPTY", symbol, qty, 0, dbPath, "No rows written");
            return { ok:false, count:qty };

        } catch (e) {
            writeStatus("ERROR", symbol, qty, rowsWritten, dbPath, e.message || String(e));
            return { ok:false, count:qty };
        }
    }

    while (true) {
        var symbol = readSymbol();
        var now = (new Date()).getTime();

        var mustExport = (symbol !== lastSymbol) || (now - lastExportAt >= 30000);

        if (mustExport) {
            var r = exportSymbol(symbol);
            if (r.ok) {
                lastSymbol = symbol;
                lastCount = r.count;
                lastExportAt = now;
            } else {
                // Retry quickly on failure.
                lastExportAt = now - 25000;
            }
        }

        WScript.Sleep(1000);
    }
}());
