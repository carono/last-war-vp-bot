const gulp = require('gulp');
const concat = require('gulp-concat');
const log = require('fancy-log');
const colors = require('ansi-colors');
const through = require('through2');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const paths = {
    controllers: ['./Scripts/proc/*.lua']
};

gulp.task('proc', function (cb) {
    let firstFile = true;
    gulp.src(paths.controllers)
        .pipe(through.obj(function(file, _, cb) {
            if (file.isBuffer()) {
                const filename = path.basename(file.path);
                let header = `-- ${filename}\n`;
                if (firstFile) {
                    header = `--lua\n` + header;
                    firstFile = false;
                }
                const contents = header + file.contents.toString();
                file.contents = Buffer.from(contents);
            }
            cb(null, file);
        }))
        .pipe(concat('init.lua', { newLine: '\n\n' }))
        .pipe(gulp.dest('./lua'))
        .on('end', () => {
            cb();
        });
});

gulp.task('watch', function () {
    gulp.watch(paths.controllers, gulp.series('proc'));
});

gulp.task('git-check', function (done) {
    try {
        execSync('git --version', { stdio: 'ignore' });
        done();
    } catch (err) {
        console.log(
            colors.red('Git is not installed.'),
            '\n  Git, the version control system, is required to download dependencies.',
            '\n  Download git here:', colors.cyan('http://git-scm.com/downloads') + '.',
            '\n  Once git is installed, run', colors.cyan('npm install'), 'again.'
        );
        process.exit(1);
    }
});

gulp.task('default', gulp.series('proc'));
