(function () {
'use strict';

var API = 'http://127.0.0.1:8772';
var canvas, ctx, wrap;
var tf = '1H';
var symbol = 'XAUUSD';
var busy = false;

function createChart() {
    wrap = document.querySelector('.chart-canvas-wrap');
    if (!wrap) return false;

    wrap.style.position = 'relative';
    wrap.style.background = '#dcc79f';

    canvas = document.getElementById('k219DirectChart');

    if (!canvas) {
        canvas = document.createElement('canvas');
        canvas.id = 'k219DirectChart';
        canvas.style.cssText =
            'position:absolute!important;' +
            'inset:0!important;' +
            'width:100%!important;' +
            'height:100%!important;' +
            'display:block!important;' +
            'visibility:visible!important;' +
            'opacity:1!important;' +
            'z-index:50000!important;' +
            'background:#dcc79f!important;';

        wrap.appendChild(canvas);
    }

    ctx = canvas.getContext('2d');
    return true;
}

function number(v) {
    v = Number(v);
    return Number.isFinite(v) ? v : null;
}

function formatPrice(v) {
    return Number(v).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

function resize() {
    if (!canvas || !wrap) return null;

    var rect = wrap.getBoundingClientRect();
    var w = Math.max(300, Math.round(rect.width));
    var h = Math.max(180, Math.round(rect.height));
    var dpr = Math.max(1, window.devicePixelRatio || 1);

    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { w:w, h:h };
}

function message(text) {
    var z = resize();
    if (!z) return;

    ctx.fillStyle = '#dcc79f';
    ctx.fillRect(0, 0, z.w, z.h);
    ctx.fillStyle = '#594a36';
    ctx.font = 'bold 14px Arial';
    ctx.textAlign = 'center';
    ctx.fillText(text, z.w / 2, z.h / 2);
}

function draw(data) {
    var z = resize();
    if (!z) return;

    var rows = (data.bars || []).map(function (x) {
        return {
            t: number(x.t),
            o: number(x.o),
            h: number(x.h),
            l: number(x.l),
            c: number(x.c)
        };
    }).filter(function (x) {
        return [x.t,x.o,x.h,x.l,x.c].every(Number.isFinite);
    }).slice(-120);

    if (!rows.length) {
        message('WAITING FOR AMIBROKER CANDLES');
        return;
    }

    var w = z.w;
    var h = z.h;
    var left = 12;
    var right = 76;
    var top = 12;
    var bottom = 28;
    var plotW = w - left - right;
    var plotH = h - top - bottom;

    var low = Math.min.apply(null, rows.map(function(x){ return x.l; }));
    var high = Math.max.apply(null, rows.map(function(x){ return x.h; }));
    var range = high - low;

    if (!(range > 0)) range = 1;

    low -= range * 0.06;
    high += range * 0.06;
    range = high - low;

    function y(price) {
        return top + ((high - price) / range) * plotH;
    }

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#dcc79f';
    ctx.fillRect(0, 0, w, h);

    ctx.strokeStyle = 'rgba(80,65,45,.20)';
    ctx.lineWidth = 1;
    ctx.font = '10px Arial';

    for (var g = 0; g <= 5; g++) {
        var gy = top + plotH * g / 5;

        ctx.beginPath();
        ctx.moveTo(left, gy);
        ctx.lineTo(left + plotW, gy);
        ctx.stroke();

        var price = high - range * g / 5;
        ctx.fillStyle = '#584b39';
        ctx.textAlign = 'left';
        ctx.fillText(formatPrice(price), left + plotW + 6, gy + 3);
    }

    var slot = plotW / rows.length;
    var body = Math.max(2, Math.min(8, slot * 0.70));

    rows.forEach(function (bar, i) {
        var x = left + (i + 0.5) * slot;
        var up = bar.c >= bar.o;
        var color = up ? '#063dff' : '#ef1919';

        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 1.2;

        ctx.beginPath();
        ctx.moveTo(x, y(bar.h));
        ctx.lineTo(x, y(bar.l));
        ctx.stroke();

        var yo = y(bar.o);
        var yc = y(bar.c);
        ctx.fillRect(
            x - body / 2,
            Math.min(yo, yc),
            body,
            Math.max(2, Math.abs(yc - yo))
        );
    });

    var last = rows[rows.length - 1];
    var py = y(last.c);

    ctx.strokeStyle = '#b8860b';
    ctx.setLineDash([4,3]);
    ctx.beginPath();
    ctx.moveTo(left, py);
    ctx.lineTo(left + plotW, py);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = '#143b91';
    ctx.fillRect(left + plotW + 2, py - 9, 70, 18);
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 10px Arial';
    ctx.textAlign = 'center';
    ctx.fillText(formatPrice(last.c), left + plotW + 37, py + 3);

    ctx.fillStyle = '#584b39';
    ctx.font = '10px Arial';
    ctx.textAlign = 'center';

    for (var n = 0; n < rows.length; n += Math.max(1, Math.floor(rows.length / 6))) {
        var d = new Date(rows[n].t);
        var label =
            String(d.getHours()).padStart(2,'0') + ':' +
            String(d.getMinutes()).padStart(2,'0');

        ctx.fillText(label, left + (n + 0.5) * slot, h - 8);
    }

    var state = document.getElementById('chartDataState');
    if (state) state.textContent = 'DB LIVE  ' + tf + '  ' + rows.length + ' BARS';

    var link = document.getElementById('chartLinkState');
    if (link) {
        link.textContent = 'DB LIVE';
        link.className = 'link-pill live';
    }
}

async function load() {
    if (busy) return;
    busy = true;

    try {
        symbol =
            String(
                (document.getElementById('chartSymbol') || {}).textContent ||
                'XAUUSD'
            ).trim().toUpperCase();

        var response = await fetch(
            API + '/api/chart?symbol=' +
            encodeURIComponent(symbol) +
            '&tf=' + encodeURIComponent(tf) +
            '&limit=500&_=' + Date.now(),
            { cache:'no-store' }
        );

        if (!response.ok) throw new Error('HTTP ' + response.status);

        var data = await response.json();

        if (!data.ok || !Array.isArray(data.bars)) {
            throw new Error('NO BARS');
        }

        draw(data);

    } catch (error) {
        message('CHART DATABASE OFFLINE  PORT 8772');
    } finally {
        busy = false;
    }
}

function detectTf(text) {
    text = String(text || '').trim().toUpperCase();

    if (text === '1H') return '1H';
    if (text === '1D') return '1D';
    if (text === '1W') return '1W';
    if (text === '1M' || text === 'M') return '1M';
    if (text === '1M LIVE' || text === 'LIVE' || text === '1MIN') return 'LIVE';

    return null;
}

function boot() {
    if (!createChart()) {
        setTimeout(boot, 300);
        return;
    }

    document.addEventListener('click', function (event) {
        var button = event.target.closest && event.target.closest('#chartTfRow button');
        if (!button) return;

        var next = detectTf(button.dataset.tf || button.textContent);
        if (!next) return;

        tf = next;
        setTimeout(load, 50);
    }, true);

    window.addEventListener('resize', function () {
        setTimeout(load, 80);
    });

    load();
    setInterval(load, 2000);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
} else {
    boot();
}

}());
