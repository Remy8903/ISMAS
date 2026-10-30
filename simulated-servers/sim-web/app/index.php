<?php
// Tiny demo app for ISMAS. Each route produces a different kind of log.

function app_log(string $level, string $msg, array $ctx = []): void {
    $line = json_encode([
        'ts'    => date('c'),
        'level' => $level,
        'msg'   => $msg,
        'path'  => $_SERVER['REQUEST_URI'] ?? '',
        'ctx'   => $ctx,
    ]);
    file_put_contents('/var/log/app/app.log', $line . PHP_EOL, FILE_APPEND);
}

function db(): PDO {
    $dsn = sprintf('mysql:host=%s;dbname=%s', getenv('DB_HOST'), getenv('DB_NAME'));
    return new PDO($dsn, getenv('DB_USER'), getenv('DB_PASS'), [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_TIMEOUT => 3,
    ]);
}

$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
header('Content-Type: application/json');

switch ($path) {
    case '/':
    case '/health':
        app_log('info', 'health ok');
        echo json_encode(['status' => 'ok']);
        break;

    case '/error':          // handled 500
        app_log('error', 'Simulated application error', ['code' => 'E_DEMO']);
        http_response_code(500);
        echo json_encode(['error' => 'simulated error']);
        break;

    case '/slow':           // slow request: /slow?s=5
        $s = min((int)($_GET['s'] ?? 3), 25);
        sleep($s);
        app_log('warning', "Slow request took {$s}s");
        echo json_encode(['slept' => $s]);
        break;

    case '/db':             // depends on sim-db -> great for correlation
        try {
            $v = db()->query('SELECT NOW() AS now')->fetch(PDO::FETCH_ASSOC);
            app_log('info', 'db query ok');
            echo json_encode(['db' => 'ok', 'now' => $v['now']]);
        } catch (Throwable $e) {
            app_log('critical', 'Database connection failed', ['error' => $e->getMessage()]);
            http_response_code(500);
            echo json_encode(['error' => 'db unavailable']);
        }
        break;

    case '/db-slow':        // slow query -> shows up in sim-db slow log
        try {
            db()->query('SELECT SLEEP(2)');
            echo json_encode(['db' => 'slow query done']);
        } catch (Throwable $e) {
            app_log('critical', 'Database connection failed', ['error' => $e->getMessage()]);
            http_response_code(500);
        }
        break;

    case '/crash':          // uncaught fatal -> PHP error log
        app_log('critical', 'About to crash');
        undefined_function_ismas();
        break;

    default:
        http_response_code(404);
        echo json_encode(['error' => 'not found']);
}
