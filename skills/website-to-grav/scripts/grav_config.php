<?php
/**
 * Merge JSON into a Grav YAML file, or lint YAML/frontmatter, using Grav's own Symfony YAML.
 *
 * Usage:
 *   php grav_config.php <grav-root> merge <relative-yaml-path> <json-file|->   deep-merge (lists replace)
 *   php grav_config.php <grav-root> get   <relative-yaml-path>                print as JSON
 *   php grav_config.php <grav-root> lint  [relative-dir=user/pages]           parse every .md frontmatter + .yaml
 *
 * Examples:
 *   echo '{"pages":{"theme":"acme"}}' | php grav_config.php grav merge user/config/system.yaml -
 *   php grav_config.php grav lint user
 */

declare(strict_types=1);

[$script, $root, $command] = array_pad($argv, 3, null);
if (!$root || !$command || !is_file($root . '/vendor/autoload.php')) {
    fwrite(STDERR, "usage: php grav_config.php <grav-root> merge|get|lint ...\n");
    exit(2);
}
require $root . '/vendor/autoload.php';

use Symfony\Component\Yaml\Yaml;

function merge_recursive(array $base, array $patch): array
{
    foreach ($patch as $key => $value) {
        $isList = is_array($value) && array_is_list($value);
        if (is_array($value) && !$isList && isset($base[$key]) && is_array($base[$key]) && !array_is_list($base[$key])) {
            $base[$key] = merge_recursive($base[$key], $value);
        } elseif ($value === null) {
            unset($base[$key]);
        } else {
            $base[$key] = $value;
        }
    }

    return $base;
}

if ($command === 'merge' || $command === 'get') {
    $file = $root . '/' . ($argv[3] ?? '');
    $current = is_file($file) ? (Yaml::parseFile($file) ?? []) : [];
    if ($command === 'get') {
        echo json_encode($current, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE), "\n";
        exit(0);
    }
    $source = $argv[4] ?? '-';
    $patch = json_decode($source === '-' ? stream_get_contents(STDIN) : file_get_contents($source), true, 512, JSON_THROW_ON_ERROR);
    $merged = merge_recursive($current, $patch);
    if (!is_dir(dirname($file))) {
        mkdir(dirname($file), 0775, true);
    }
    file_put_contents($file, Yaml::dump($merged, 10, 2, Yaml::DUMP_MULTI_LINE_LITERAL_BLOCK));
    echo "merged into {$argv[3]}\n";
    exit(0);
}

if ($command === 'lint') {
    $directory = $root . '/' . ($argv[3] ?? 'user/pages');
    $failures = 0;
    $count = 0;
    $iterator = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($directory, FilesystemIterator::SKIP_DOTS));
    foreach ($iterator as $file) {
        $path = $file->getPathname();
        if (preg_match('#/(node_modules|vendor|plugins|tests)/#', $path)) {
            continue;
        }
        $extension = $file->getExtension();
        if (!in_array($extension, ['md', 'yaml', 'yml'], true)) {
            continue;
        }
        $content = file_get_contents($path);
        if ($extension === 'md') {
            if (!preg_match('/^---\R(.*?)\R---(\R|$)/s', $content, $match)) {
                continue;
            }
            $content = $match[1];
        }
        $count++;
        try {
            Yaml::parse($content);
        } catch (Throwable $error) {
            $failures++;
            fwrite(STDERR, "YAML error in {$path}: {$error->getMessage()}\n");
        }
    }
    echo "linted {$count} files, {$failures} failed\n";
    exit($failures ? 1 : 0);
}

fwrite(STDERR, "unknown command {$command}\n");
exit(2);
