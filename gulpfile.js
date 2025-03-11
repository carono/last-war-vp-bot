const gulp = require('gulp');
const concat = require('gulp-concat');
const log = require('fancy-log');
const colors = require('ansi-colors');
const fs = require('fs');
const { execSync } = require('child_process');

const paths = {
    controllers: ['./Scripts/proc/*.lua']
};

gulp.task('proc', function (cb) {
    gulp.src(paths.controllers)
        .pipe(concat('init.lua', { newLine: '\n\n' }))
        .pipe(gulp.dest('./lua'))
        .on('end', () => {
            fs.writeFileSync('./Scripts/reload.tmp', '1');
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
